import os
import json
from requests_oauthlib import OAuth1Session

from config import ACCESS_TOKEN_URL, AUTHORIZE_URL, BALDURS_GATE_CAMPAIGN_ID, CONSUMER_KEY, CONSUMER_SECRET, \
    QDRANT_COLLECTION_NAME, QDRANT_URL, REQUEST_TOKEN_URL
from ingest import Document, prepare_document_points, upsert_points

# load_dotenv(r"D:\dev\lorekeeper\.env")
#
# CONSUMER_KEY = os.environ["CONSUMER_KEY"]
# CONSUMER_SECRET = os.environ["CONSUMER_SECRET"]
# REQUEST_TOKEN_URL = os.environ["REQUEST_TOKEN_URL"]
# ACCESS_TOKEN_URL = os.environ["ACCESS_TOKEN_URL"]
# AUTHORIZE_URL = os.environ["AUTHORIZE_URL"]
USER_AGENT = 'ObsidianPortalOAuthTest/1.0'
TOKEN_PATH = os.path.join(os.path.dirname(__file__), '.op_token.json')

def save_token(token_dict):
    with open(TOKEN_PATH, 'w') as f:
        json.dump(token_dict, f)

def load_token():
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, 'r') as f:
            return json.load(f)
    return None

def get_authenticated_session():
    token = load_token()
    if token:
        session = OAuth1Session(
            CONSUMER_KEY,
            client_secret=CONSUMER_SECRET,
            resource_owner_key=token['oauth_token'],
            resource_owner_secret=token['oauth_token_secret']
        )
        session.headers.update({'User-Agent': USER_AGENT})
        return session

    # Step 1: Get request token
    oauth = OAuth1Session(
        CONSUMER_KEY,
        client_secret=CONSUMER_SECRET,
        callback_uri='oob'
    )
    oauth.headers.update({'User-Agent': USER_AGENT})
    fetch_response = oauth.fetch_request_token(REQUEST_TOKEN_URL)
    resource_owner_key = fetch_response.get('oauth_token')
    resource_owner_secret = fetch_response.get('oauth_token_secret')

    # Step 2: Authorize user
    print(f"Go to the following URL and authorize the app:")
    print(f"{AUTHORIZE_URL}?oauth_token={resource_owner_key}")
    verifier = input("Enter the provided verifier (PIN): ").strip()

    # Step 3: Get access token
    oauth = OAuth1Session(
        CONSUMER_KEY,
        client_secret=CONSUMER_SECRET,
        resource_owner_key=resource_owner_key,
        resource_owner_secret=resource_owner_secret,
        verifier=verifier
    )
    oauth.headers.update({'User-Agent': USER_AGENT})
    oauth_tokens = oauth.fetch_access_token(ACCESS_TOKEN_URL)
    access_token = oauth_tokens['oauth_token']
    access_token_secret = oauth_tokens['oauth_token_secret']
    save_token({'oauth_token': access_token, 'oauth_token_secret': access_token_secret})

    # Step 4: Return authenticated session
    session = OAuth1Session(
        CONSUMER_KEY,
        client_secret=CONSUMER_SECRET,
        resource_owner_key=access_token,
        resource_owner_secret=access_token_secret
    )
    session.headers.update({'User-Agent': USER_AGENT})
    return session
