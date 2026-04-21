import asyncio
import json
import os

from pydantic import BaseModel, Field
from requests_oauthlib import OAuth1Session

from lorekeeper.config import settings

USER_AGENT = "ObsidianPortalOAuthTest/1.0"
TOKEN_PATH = os.path.join(os.path.dirname(__file__), ".op_token.json")


class AccessToken(BaseModel):
    token: str = Field(validation_alias="oauth_token")
    secret: str = Field(validation_alias="oauth_token_secret")


async def get_authenticated_session_async() -> OAuth1Session:
    return await asyncio.to_thread(get_authenticated_session)


def get_authenticated_session() -> OAuth1Session:
    token = _load_token()
    if token is None:
        request_token = _get_request_token()
        verifier = _authorize_user(request_token)
        token = _get_access_token(request_token, verifier)
        _save_token(token)

    session = OAuth1Session(
        settings.consumer_key,
        client_secret=settings.consumer_secret,
        resource_owner_key=token.token,
        resource_owner_secret=token.secret,
    )
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _load_token() -> AccessToken | None:
    env_token = os.environ.get("OP_OAUTH_TOKEN")
    env_secret = os.environ.get("OP_OAUTH_TOKEN_SECRET")
    if env_token and env_secret:
        return AccessToken.model_validate({"oauth_token": env_token, "oauth_token_secret": env_secret})
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, encoding="utf-8") as f:
            obj = json.load(f)
        return AccessToken.model_validate(obj)
    return None


def _save_token(token: AccessToken) -> None:
    with open(TOKEN_PATH, "w", encoding="utf-8") as f:
        json.dump(token.model_dump(by_alias=True), f)


def _get_request_token() -> AccessToken:
    oauth = OAuth1Session(settings.consumer_key, client_secret=settings.consumer_secret, callback_uri="oob")
    oauth.headers.update({"User-Agent": USER_AGENT})
    request_token = oauth.fetch_request_token(settings.request_token_url)
    return AccessToken.model_validate(request_token)


def _authorize_user(request_token: AccessToken) -> str:
    print("Go to the following URL and authorize the app:")
    print(f"{settings.authorize_url}?oauth_token={request_token.token}")
    verifier = input("Enter the provided verifier (PIN): ").strip()
    return verifier


def _get_access_token(request_token: AccessToken, verifier: str) -> AccessToken:
    oauth = OAuth1Session(
        settings.consumer_key,
        client_secret=settings.consumer_secret,
        resource_owner_key=request_token.token,
        resource_owner_secret=request_token.secret,
        verifier=verifier,
    )
    oauth.headers.update({"User-Agent": USER_AGENT})
    oauth_tokens = oauth.fetch_access_token(settings.access_token_url)
    return AccessToken.model_validate(oauth_tokens)
