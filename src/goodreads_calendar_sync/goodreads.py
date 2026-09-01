import json
import logging
import pickle
import re
import time
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

from .config import (
    GOODREADS_PASSWORD,
    GOODREADS_EMAIL,
    GOODREADS_SHELF_NAME,
    GOODREADS_SHELF_URL,
    GOODREADS_USER_ID,
    SHELF_BASE_URL,
    SHELF_PAGE_SIZE,
    STATE_FILE,
)
from .types import BookInfo


PLACEHOLDER_TEXT = {'unknown', 'n/a', '-', 'untitled'}
COOKIES_FILE = Path(STATE_FILE).parent / 'goodreads_cookies.pkl'


def _is_placeholder_text(value: Optional[str]) -> bool:
    if value is None:
        return False
    return value.strip().lower() in PLACEHOLDER_TEXT


def _normalize_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = value.strip()
    if not text or _is_placeholder_text(text):
        return None
    return text


def _extract_book_id_from_url(url: str) -> Optional[str]:
    match = re.search(r'/book/show/(\d+)', url)
    return match.group(1) if match else None


def _parse_iso_date(text: str) -> Optional[date]:
    if not text:
        return None

    normalized = text.strip()
    normalized = re.sub(r'\s+', ' ', normalized)
    normalized = re.sub(r'(?i)(Expected|Not yet published|Published|Release date|Publication date|publication date|expected)[:\s]*', '', normalized)
    normalized = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', normalized)

    try:
        parsed = parse_datetime(normalized, fuzzy=True, default=datetime(2000, 1, 1))
        if parsed.year < 1900:
            parsed = parsed.replace(year=parsed.year + 2000)
        return parsed.date()
    except Exception:
        return None


def _parse_series_from_page(soup: BeautifulSoup) -> Optional[str]:
    anchor = soup.select_one('a[href*="/series/"]')
    if anchor:
        return _normalize_text(anchor.get_text())

    og_description = soup.select_one('meta[property="og:description"]')
    if og_description and og_description.has_attr('content'):
        match = re.search(r'Book \d+ in the (.+?) series', og_description['content'])
        if match:
            return match.group(1).strip()

    return None


def _parse_pre_release_date(soup: BeautifulSoup) -> Optional[date]:
    container = soup.select_one('.PreReleaseDetails')
    if container is None:
        return None

    text = ' '.join(container.stripped_strings)
    return _parse_iso_date(text)


def _parse_jsonld_metadata(soup: BeautifulSoup) -> Dict[str, Optional[str]]:
    metadata: Dict[str, Optional[str]] = {}
    script = soup.select_one('script[type="application/ld+json"]')
    if script is None or not script.string:
        return metadata

    try:
        payload = json.loads(script.string)
    except json.JSONDecodeError:
        return metadata

    if isinstance(payload, dict) and payload.get('@type') == 'Book':
        metadata['title'] = _normalize_text(payload.get('name'))
        metadata['isbn'] = _normalize_text(payload.get('isbn'))
        author_value = payload.get('author')
        if isinstance(author_value, list) and author_value:
            metadata['author'] = _normalize_text(author_value[0].get('name'))
        elif isinstance(author_value, dict):
            metadata['author'] = _normalize_text(author_value.get('name'))

    return metadata


class GoodreadsClient:
    def __init__(
        self,
        email: str = GOODREADS_EMAIL,
        password: str = GOODREADS_PASSWORD,
        user_id: Optional[str] = GOODREADS_USER_ID,
        shelf_url: Optional[str] = GOODREADS_SHELF_URL,
    ):
        self.email = email
        self.password = password
        self.user_id = user_id
        self.shelf_url = shelf_url
        self.session = requests.Session()
        self.session.headers.update(
            {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-User': '?1',
            }
        )
        self._configure_retry()

    def _configure_retry(self) -> None:
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(['GET', 'POST']),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)

    def _load_session_cookies(self) -> bool:
        try:
            with open(COOKIES_FILE, 'rb') as f:
                cookies = pickle.load(f)
                self.session.cookies.update(cookies)
                logger.info('Loaded persisted session cookies')
                return True
        except FileNotFoundError:
            logger.info('No persisted session cookies found')
            return False
        except Exception as exc:
            logger.warning('Failed to load session cookies: %s', exc)
            return False

    def save_session_cookies(self) -> None:
        try:
            with open(COOKIES_FILE, 'wb') as f:
                pickle.dump(self.session.cookies, f)
                logger.info('Saved session cookies for future runs')
        except Exception as exc:
            logger.warning('Failed to save session cookies: %s', exc)

    def _clear_session_cookies(self) -> None:
        self.session.cookies.clear()
        logger.info('Cleared session cookies')

    def _test_session_cookies(self, shelf_url: str) -> bool:
        try:
            response = self._get(shelf_url)
            soup = BeautifulSoup(response.text, 'html.parser')
            if self._is_signin_page(response.text, response.url):
                logger.info('Session cookies expired or invalid')
                return False
            logger.info('Session cookies are still valid')
            return True
        except Exception as exc:
            logger.warning('Error testing session cookies: %s', exc)
            return False

    def _build_shelf_url(self, page: int = 1) -> str:
        if self.shelf_url:
            parsed = urlparse(self.shelf_url)
            query = dict(parse_qsl(parsed.query, keep_blank_values=True))
            query.setdefault('view', 'table')
            query.setdefault('per_page', str(SHELF_PAGE_SIZE))
            if page > 1:
                query['page'] = str(page)
            elif 'page' in query:
                query.pop('page', None)
            url = urlunparse(parsed._replace(query=urlencode(query, doseq=True)))
        else:
            if not self.user_id:
                raise ValueError('GOODREADS_USER_ID or GOODREADS_SHELF_URL is required')

            query = f'?shelf={GOODREADS_SHELF_NAME}&view=table&per_page={SHELF_PAGE_SIZE}&page={page}'
            url = f'{SHELF_BASE_URL}/{self.user_id}{query}'

        logger.debug('Built Goodreads shelf URL: %s', url)
        return url

    def _get(self, url: str):
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        return response

    def _post(self, url: str, data: Dict[str, str], headers: Optional[Dict[str, str]] = None):
        response = self.session.post(url, data=data, headers=headers, timeout=30)
        response.raise_for_status()
        return response

    def _find_ap_signin_url(self, html: str) -> Optional[str]:
        soup = BeautifulSoup(html, 'html.parser')
        candidate_url: Optional[str] = None
        for link in soup.select('a[href*="/ap/signin"]'):
            href = link.get('href')
            if not href:
                continue
            normalized = href.replace('&amp;', '&')
            if 'identityProvider=' not in normalized:
                return urljoin('https://www.goodreads.com', normalized)
            if candidate_url is None:
                candidate_url = normalized
        if candidate_url:
            return urljoin('https://www.goodreads.com', candidate_url)
        return None

    def _parse_email_signin_form(self, html: str) -> Tuple[Optional[str], Dict[str, str]]:
        soup = BeautifulSoup(html, 'html.parser')
        for form in soup.find_all('form'):
            if form.find('input', attrs={'name': 'email'}) and form.find('input', attrs={'name': 'password'}):
                action = form.get('action')
                if not action:
                    continue
                action = urljoin('https://www.goodreads.com', action)
                payload: Dict[str, str] = {}
                for input_tag in form.find_all('input'):
                    name = input_tag.get('name')
                    if not name:
                        continue
                    value = input_tag.get('value', '')
                    input_type = input_tag.get('type', '').lower()
                    if input_type == 'checkbox' and name == 'rememberMe' and not value:
                        value = 'true'
                    payload[name] = value
                return action, payload
        return None, {}

    def _is_signin_page(self, html: str, url: Optional[str] = None) -> bool:
        if url:
            path = urlparse(url).path
            if path == '/user/sign_in' or path.startswith('/ap/signin') or path.startswith('/ap/challenge') or path.startswith('/ap/forgotpassword'):
                return True
        soup = BeautifulSoup(html, 'html.parser')
        if soup.find('input', attrs={'name': 'email'}) and soup.find('input', attrs={'name': 'password'}):
            return True
        title = ''
        if soup.title and soup.title.string:
            title = soup.title.string.strip().lower()
        if 'password reset required' in title:
            return True
        if 'sign in to goodreads' in title or 'sign in to your account' in title:
            return True
        text = soup.get_text().strip().lower()
        if 'password reset required' in text or 'password assistance' in text:
            return True
        return False

    def _extract_authenticity_token(self, html: str) -> Optional[str]:
        soup = BeautifulSoup(html, 'html.parser')
        token_input = soup.find('input', attrs={'name': 'authenticity_token'})
        if token_input and token_input.has_attr('value'):
            return token_input['value']

        token_meta = soup.find('meta', attrs={'name': 'csrf-token'})
        if token_meta and token_meta.has_attr('content'):
            return token_meta['content']

        return None

    def login(self) -> None:
        if not self.email or not self.password:
            raise ValueError('Goodreads credentials are required')

        shelf_url = self._build_shelf_url(1)
        logger.info('Goodreads login: shelf URL=%s', shelf_url)

        # Try to use persisted session cookies first
        if self._load_session_cookies():
            if self._test_session_cookies(shelf_url):
                return
            logger.info('Persisted cookies invalid; clearing and performing fresh login')
            self._clear_session_cookies()

        return_url = quote(shelf_url, safe='')
        signin_page = self._get(f'https://www.goodreads.com/user/sign_in?returnurl={return_url}')

        ap_signin_url = self._find_ap_signin_url(signin_page.text)
        if ap_signin_url:
            logger.info('Found Goodreads /ap/signin email login URL')
            signin_page = self._get(ap_signin_url)
        else:
            logger.info('No Goodreads /ap/signin email login URL found; parsing initial sign-in page directly')

        action, payload = self._parse_email_signin_form(signin_page.text)
        if not action:
            raise RuntimeError('Could not locate Goodreads email sign-in form')

        payload['email'] = self.email
        payload['password'] = self.password
        if 'rememberMe' in payload and not payload.get('rememberMe'):
            payload['rememberMe'] = 'true'

        response = self._post(action, payload, headers={'Referer': signin_page.url, 'Origin': 'https://www.goodreads.com'})
        logger.info(
            'Goodreads login POST response: status=%s final URL=%s history=%s',
            response.status_code,
            response.url,
            [r.status_code for r in response.history],
        )
        if self._is_signin_page(response.text, response.url):
            logger.info(
                'Login POST response still looks like sign-in page; final URL=%s; snippet=%s',
                response.url,
                response.text[:400].replace('\n', ' '),
            )
            raise RuntimeError(
                f'Goodreads login failed: auth flow did not complete after POST; final URL was {response.url}'
            )

        # Retry shelf page access with exponential backoff if it requires auth
        max_retries = 3
        for attempt in range(max_retries):
            try:
                shelf_response = self._get(shelf_url)
                soup = BeautifulSoup(shelf_response.text, 'html.parser')
                page_title = soup.title.string.strip() if soup.title and soup.title.string else None
                logger.info('Loaded shelf URL: status=%s final URL=%s title=%r', shelf_response.status_code, shelf_response.url, page_title)
                
                if not self._is_signin_page(shelf_response.text, shelf_response.url):
                    logger.info('Goodreads shelf page accessed successfully after login')
                    return
                
                # Shelf page requires auth - retry with backoff
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # 1s, 2s, 4s
                    logger.warning(
                        'Shelf page requires auth (attempt %d/%d); waiting %ds before retry',
                        attempt + 1,
                        max_retries,
                        wait_time,
                    )
                    time.sleep(wait_time)
                else:
                    logger.info(
                        'Shelf page still requires auth after all retries; title=%r; snippet=%s',
                        page_title,
                        shelf_response.text[:300].replace('\n', ' '),
                    )
                    raise RuntimeError('Goodreads login failed: shelf page still requires auth after retries')
            except requests.RequestException as exc:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning(
                        'Request error loading shelf (attempt %d/%d): %s; waiting %ds before retry',
                        attempt + 1,
                        max_retries,
                        exc,
                        wait_time,
                    )
                    time.sleep(wait_time)
                else:
                    raise RuntimeError(f'Goodreads login failed: could not load shelf after retries: {exc}')

    def _find_feed_url(self, html: str) -> Optional[str]:
        soup = BeautifulSoup(html, 'html.parser')
        alternate = soup.find('link', attrs={'rel': 'alternate', 'type': 'application/atom+xml'})
        feed_url = None
        if alternate and alternate.has_attr('href'):
            feed_url = urljoin('https://www.goodreads.com', alternate['href'])
        logger.debug('Goodreads feed URL found: %s', feed_url)
        return feed_url

    def _has_next_page(self, html: str) -> bool:
        soup = BeautifulSoup(html, 'html.parser')
        next_page = soup.select_one('a.next_page')
        if next_page and next_page.get('href'):
            return True
        next_page = soup.find('a', rel='next')
        return bool(next_page and next_page.get('href'))

    def _parse_shelf_html(self, html: str) -> List[BookInfo]:
        soup = BeautifulSoup(html, 'html.parser')
        rows = soup.select('tr.bookalike.review')
        logger.debug('Found %d shelf rows with selector tr.bookalike.review', len(rows))
        if not rows:
            logger.debug('Fallback debug counts: title=%d author=%d isbn=%d isbn13=%d date_pub=%d date_pub_edition=%d',
                len(soup.select('td.field.title')),
                len(soup.select('td.field.author')),
                len(soup.select('td.field.isbn .value')),
                len(soup.select('td.field.isbn13 .value')),
                len(soup.select('td.field.date_pub .value')),
                len(soup.select('td.field.date_pub_edition .value')),
            )

        books: List[BookInfo] = []
        for row in rows:
            title_anchor = row.select_one('td.field.title .value a')
            if not title_anchor or not title_anchor.has_attr('href'):
                logger.debug('Skipping row without title link or href: %s', row)
                continue

            detail_path = title_anchor['href']
            detail_url = urljoin('https://www.goodreads.com', detail_path)
            book_id = _extract_book_id_from_url(detail_path)
            if not book_id:
                logger.debug('Skipping row with non-book href: %s', detail_path)
                continue

            title = _normalize_text(title_anchor.get_text()) or ''
            author_anchor = row.select_one('td.field.author .value a')
            author = _normalize_text(author_anchor.get_text()) if author_anchor else ''
            isbn = _normalize_text(row.select_one('td.field.isbn .value').get_text() if row.select_one('td.field.isbn .value') else '')
            if not isbn:
                isbn = _normalize_text(row.select_one('td.field.isbn13 .value').get_text() if row.select_one('td.field.isbn13 .value') else '')

            release_text = None
            for selector in ('td.field.date_pub_edition .value', 'td.field.date_pub .value'):
                cell = row.select_one(selector)
                if cell:
                    release_text = _normalize_text(cell.get_text())
                    if release_text:
                        break

            release_date = _parse_iso_date(release_text or '')
            if release_text and release_date is None:
                logger.debug('Unable to parse release date %r for book %s', release_text, book_id)

            books.append(
                BookInfo(
                    goodreads_id=book_id,
                    title=title,
                    author=author,
                    detail_url=detail_url,
                    goodreads_url=detail_url,
                    release_date=release_date,
                    isbn=isbn,
                )
            )

        logger.debug('Parsed %d books from shelf HTML', len(books))
        return books

    def _parse_rss_feed(self, xml_text: str) -> List[BookInfo]:
        try:
            import xml.etree.ElementTree as ET
        except ImportError:
            return []

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []

        namespaces = {
            'atom': 'http://www.w3.org/2005/Atom',
        }
        books: List[BookInfo] = []
        for entry in root.findall('.//atom:entry', namespaces):
            title = entry.findtext('atom:title', default='').strip()
            link = entry.find('atom:link', namespaces)
            href = link.attrib.get('href') if link is not None else None
            if not href:
                continue
            book_id = _extract_book_id_from_url(href)
            if not book_id:
                continue
            author = ''
            if ' by ' in title:
                parts = title.rsplit(' by ', 1)
                title, author = parts[0].strip(), parts[1].strip()

            books.append(
                BookInfo(
                    goodreads_id=book_id,
                    title=title,
                    author=author,
                    detail_url=href,
                    goodreads_url=href,
                )
            )

        return books

    def get_to_read_books(self) -> List[BookInfo]:
        books: List[BookInfo] = []
        page = 1
        while True:
            url = self._build_shelf_url(page)
            logger.debug('Fetching Goodreads shelf page %d: %s', page, url)
            response = self._get(url)
            html = response.text
            logger.debug('Fetched page %d HTML length: %d', page, len(html))

            if page == 1:
                feed_url = self._find_feed_url(html)
                if feed_url:
                    feed_books = self._parse_rss_feed(self._get(feed_url).text)
                    logger.debug('Parsed %d books from Goodreads RSS feed', len(feed_books))
                    if feed_books:
                        books = feed_books

            page_books = self._parse_shelf_html(html)
            logger.debug('Page %d produced %d shelf books', page, len(page_books))
            if page_books:
                existing_ids = {book.goodreads_id for book in books}
                for book in page_books:
                    if book.goodreads_id not in existing_ids:
                        books.append(book)

            if not page_books:
                break
            if not self._has_next_page(html):
                break
            page += 1

        logger.debug('Total books found: %d', len(books))
        return books

    def refresh_book_details(self, book: BookInfo) -> None:
        response = self._get(book.detail_url)
        soup = BeautifulSoup(response.text, 'html.parser')

        metadata = _parse_jsonld_metadata(soup)
        if metadata.get('title'):
            book.title = metadata['title']
        if metadata.get('author'):
            book.author = metadata['author']
        if metadata.get('isbn'):
            book.isbn = metadata['isbn']

        if book.title == '':
            title_tag = soup.select_one('h1')
            if title_tag:
                book.title = _normalize_text(title_tag.get_text()) or book.title

        if not book.author:
            author_tag = soup.select_one('a[href*="/author/show/"]')
            if author_tag:
                book.author = _normalize_text(author_tag.get_text()) or book.author

        series = _parse_series_from_page(soup)
        if series:
            book.series = series

        if book.release_date is None:
            book.release_date = _parse_pre_release_date(soup)

        if book.release_date is None:
            full_text = soup.get_text(separator=' ', strip=True)
            match = re.search(r'Published\s+(.*?\d{4})', full_text)
            if match:
                book.release_date = _parse_iso_date(match.group(1))

        book.last_checked = datetime.utcnow()
