import json
import os

from pydantic import BaseModel, Field
from requests_oauthlib import OAuth1Session

from config import ACCESS_TOKEN_URL, AUTHORIZE_URL, CONSUMER_KEY, CONSUMER_SECRET, REQUEST_TOKEN_URL

USER_AGENT = 'ObsidianPortalOAuthTest/1.0'
TOKEN_PATH = os.path.join(os.path.dirname(__file__), '.op_token.json')


class AccessToken(BaseModel):
    token: str = Field(validation_alias="oauth_token")
    secret: str = Field(validation_alias="oauth_token_secret")


def _save_token(token: AccessToken) -> None:
    with open(TOKEN_PATH, 'w') as f:
        json.dump(token.model_dump(by_alias=True), f)


def _load_token() -> AccessToken | None:
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, 'r') as f:
            obj = json.load(f)
        return AccessToken.model_validate(obj)
    return None


def get_authenticated_session() -> OAuth1Session:
    token = _load_token()
    if token is None:
        request_token = _get_request_token()
        verifier = _authorize_user(request_token)
        token = _get_access_token(request_token, verifier)
        _save_token(token)

    session = OAuth1Session(
        CONSUMER_KEY,
        client_secret=CONSUMER_SECRET,
        resource_owner_key=token.token,
        resource_owner_secret=token.secret,
    )
    session.headers.update({'User-Agent': USER_AGENT})
    return session


def _get_request_token() -> AccessToken:
    oauth = OAuth1Session(
        CONSUMER_KEY,
        client_secret=CONSUMER_SECRET,
        callback_uri='oob'
    )
    oauth.headers.update({'User-Agent': USER_AGENT})
    request_token = oauth.fetch_request_token(REQUEST_TOKEN_URL)
    return AccessToken.model_validate(request_token)


def _authorize_user(request_token: AccessToken) -> str:
    print(f"Go to the following URL and authorize the app:")
    print(f"{AUTHORIZE_URL}?oauth_token={request_token.token}")
    verifier = input("Enter the provided verifier (PIN): ").strip()
    return verifier


def _get_access_token(request_token: AccessToken, verifier: str) -> AccessToken:
    oauth = OAuth1Session(
        CONSUMER_KEY,
        client_secret=CONSUMER_SECRET,
        resource_owner_key=request_token.token,
        resource_owner_secret=request_token.secret,
        verifier=verifier
    )
    oauth.headers.update({'User-Agent': USER_AGENT})
    oauth_tokens = oauth.fetch_access_token(ACCESS_TOKEN_URL)
    return AccessToken.model_validate(oauth_tokens)
