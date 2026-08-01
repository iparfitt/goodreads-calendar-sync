from datetime import date, datetime
from pathlib import Path

from goodreads_calendar_sync.goodreads import (
    GoodreadsClient,
    _extract_book_id_from_url,
    _is_placeholder_text,
    _parse_iso_date,
)
from goodreads_calendar_sync.sync import _is_past_release


def test_extract_book_id_from_url():
    assert _extract_book_id_from_url('/book/show/252778343-beneath-a-midnight-moon') == '252778343'

def test_parse_iso_date_expected():
    assert _parse_iso_date('Expected 17 Nov 26') == date(2026, 11, 17)


def test_parse_iso_date_long_form():
    assert _parse_iso_date('Jan 10, 2026') == date(2026, 1, 10)


def test_past_release_is_marked_immutable():
    assert _is_past_release(date(2020, 1, 1))
    assert not _is_past_release(date(2099, 1, 1))


def test_find_ap_signin_url_prefers_email_login():
    html = '''
        <html>
          <body>
            <a href="https://www.goodreads.com/ap/signin?identityProvider=LoginWithAmazon&language=en_US">Amazon</a>
            <a href="https://www.goodreads.com/ap/signin?identityProvider=APPLE&language=en_US">Apple</a>
            <a href="https://www.goodreads.com/ap/signin?identityProvider=GOOGLE&language=en_US">Google</a>
            <a href="/ap/signin?language=en_US&openid.assoc_handle=amzn_goodreads_web_na&openid.return_to=https%3A%2F%2Fwww.goodreads.com%2Fap-handler%2Fsign-in">Sign in with email</a>
          </body>
        </html>
    '''
    client = GoodreadsClient(email='x', password='y', user_id='102479483')
    assert client._find_ap_signin_url(html) == 'https://www.goodreads.com/ap/signin?language=en_US&openid.assoc_handle=amzn_goodreads_web_na&openid.return_to=https%3A%2F%2Fwww.goodreads.com%2Fap-handler%2Fsign-in'


def test_parse_email_signin_form_extracts_hidden_fields():
    html = '''
        <html>
          <body>
            <form action="/ap/signin/1234" method="post">
              <input type="hidden" name="appActionToken" value="abc" />
              <input type="hidden" name="siteState" value="xyz" />
              <input type="email" name="email" value="" />
              <input type="password" name="password" value="" />
              <input type="checkbox" name="rememberMe" value="" />
            </form>
          </body>
        </html>
    '''
    client = GoodreadsClient(email='x', password='y', user_id='102479483')
    action, payload = client._parse_email_signin_form(html)
    assert action == 'https://www.goodreads.com/ap/signin/1234'
    assert payload['appActionToken'] == 'abc'
    assert payload['siteState'] == 'xyz'
    assert payload['rememberMe'] == 'true'


def test_is_signin_page_detects_email_signin_form():
    html = '''
        <html>
          <head><title>Goodreads Sign in</title></head>
          <body>
            <form action="/ap/signin" method="post">
              <input type="email" name="email" />
              <input type="password" name="password" />
            </form>
          </body>
        </html>
    '''
    client = GoodreadsClient(email='x', password='y', user_id='102479483')
    assert client._is_signin_page(html, 'https://www.goodreads.com/ap/signin')


def test_is_signin_page_handles_missing_title():
    html = '''
        <html>
          <body>
            <form action="/ap/signin" method="post">
              <input type="email" name="email" />
              <input type="password" name="password" />
            </form>
          </body>
        </html>
    '''
    client = GoodreadsClient(email='x', password='y', user_id='102479483')
    assert client._is_signin_page(html)


def test_is_signin_page_detects_password_reset_challenge():
    html = '''
        <html>
          <head><title>Password reset required</title></head>
          <body>
            <p>Please set a new password for your account that you have not used elsewhere.</p>
          </body>
        </html>
    '''
    client = GoodreadsClient(email='x', password='y', user_id='102479483')
    assert client._is_signin_page(html, 'https://www.goodreads.com/ap/forgotpassword/reverification')


def test_is_signin_page_does_not_false_positive_on_homepage():
    html = '''
        <html>
          <head><title>Goodreads</title></head>
          <body>
            <a href="/user/sign_in">Sign in</a>
            <p>Welcome to Goodreads.</p>
          </body>
        </html>
    '''
    client = GoodreadsClient(email='x', password='y', user_id='102479483')
    assert not client._is_signin_page(html, 'https://www.goodreads.com/')


def test_parse_shelf_html_reads_books():
    client = GoodreadsClient(email='x', password='y', user_id='102479483')
    html = '''
        <table>
          <tr class="bookalike review">
            <td class="field title"><div class="value"><a href="/book/show/239641042-example-book">Example Book</a></div></td>
            <td class="field author"><div class="value"><a href="/author/show/1">Example Author</a></div></td>
            <td class="field.isbn"><div class="value">9781234567890</div></td>
            <td class="field date_pub"><div class="value">Jan 10, 2026</div></td>
          </tr>
        </table>
    '''
    books = client._parse_shelf_html(html)

    assert any(book.goodreads_id == '239641042' for book in books)
    first_book = books[0]
    assert first_book.detail_url.startswith('https://www.goodreads.com/book/show/')
    assert first_book.title
    assert first_book.author


from goodreads_calendar_sync.goodreads import _normalize_text


def test_normalize_text_treats_untitled_as_missing():
    assert _normalize_text('  Untitled  ') is None


def test_placeholder_title_exact_match_only():
    assert _is_placeholder_text('untitled')
    assert not _is_placeholder_text('The Untitled Book')


from urllib.parse import parse_qs, urlparse


def test_build_shelf_url_preserves_page_on_custom_url():
    client = GoodreadsClient(email='x', password='y', shelf_url='https://www.goodreads.com/review/list/102479483?sort=author')
    url1 = client._build_shelf_url(1)
    url2 = client._build_shelf_url(2)

    assert 'sort=author' in url1
    parsed1 = urlparse(url1)
    query1 = parse_qs(parsed1.query)
    assert 'page' not in query1
    assert query1.get('view', [''])[0] == 'table'
    assert query1.get('per_page', [''])[0] == '200'

    parsed2 = urlparse(url2)
    query2 = parse_qs(parsed2.query)
    assert query2.get('page', [''])[0] == '2'


def test_build_shelf_url_adds_per_page_when_missing():
    client = GoodreadsClient(email='x', password='y', shelf_url='https://www.goodreads.com/review/list/102479483?shelf=to-read')
    assert 'per_page=200' in client._build_shelf_url(1)
    assert 'view=table' in client._build_shelf_url(1)


def test_has_next_page_detects_next_page_link():
    html = '<html><body><a class="next_page" href="/review/list/102479483?page=2">next »</a></body></html>'
    client = GoodreadsClient(email='x', password='y')
    assert client._has_next_page(html)


def test_has_next_page_handles_no_next_page():
    html = '<html><body><p>No more pages</p></body></html>'
    client = GoodreadsClient(email='x', password='y')
    assert not client._has_next_page(html)


def test_sync_preserves_state_on_empty_goodreads_response():
    from goodreads_calendar_sync.sync import run_sync
    from goodreads_calendar_sync.state import load_state, save_state
    from goodreads_calendar_sync.types import StoredBook
    from unittest.mock import patch

    state_path = Path(__file__).resolve().parents[1] / 'state.json'
    record = StoredBook(
        goodreads_id='12345',
        title='Saved Book',
        author='Saved Author',
        release_date=None,
        isbn='9781234567890',
        series='Saved Series',
        calendar_uid='goodreads-12345',
        last_checked=datetime.utcnow(),
    )
    save_state(state_path, {'12345': record})

    with patch('goodreads_calendar_sync.sync.GoodreadsClient.get_to_read_books', return_value=[]), \
         patch('goodreads_calendar_sync.sync.GoodreadsClient.login', return_value=None):
        run_sync()

    loaded = load_state(state_path)
    assert '12345' in loaded

def test_event_uid_parses_from_event_data():
    from goodreads_calendar_sync.apple_calendar import AppleCalendarClient

    event = type('Event', (), {'data': 'BEGIN:VCALENDAR\nUID:goodreads-12345\nEND:VCALENDAR'})
    client = object.__new__(AppleCalendarClient)
    assert client._event_uid(event) == 'goodreads-12345'


def test_get_calendar_reuses_existing_calendar():
    from goodreads_calendar_sync.apple_calendar import AppleCalendarClient

    class CalendarMock:
        def get_display_name(self):
            return 'Book Releases'

    principal = type('PrincipalMock', (), {'calendars': lambda self: [CalendarMock()]})()
    client = object.__new__(AppleCalendarClient)
    client.principal = principal

    calendar = client._get_calendar('Book Releases')
    assert calendar is not None
    assert calendar.get_display_name() == 'Book Releases'


def test_escape_ics_text_decodes_html_entities():
    from goodreads_calendar_sync.apple_calendar import _escape_ics_text

    assert _escape_ics_text("Izzy&apos;s book") == "Izzy's book"
