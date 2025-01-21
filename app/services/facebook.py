import aiohttp
import logging
from typing import Dict, Any, Optional
from urllib.parse import urljoin

logger = logging.getLogger(__name__)


class FacebookAPI:
    BASE_URL = "https://graph.facebook.com/v21.0"  # Match your API version

    def __init__(self, access_token: str):
        self.access_token = access_token

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make a request to the Facebook Graph API."""
        url = urljoin(self.BASE_URL, endpoint)

        # Always include access token
        params = {"access_token": self.access_token}

        async with aiohttp.ClientSession() as session:
            try:
                if method == "GET":
                    async with session.get(url, params=params) as response:
                        response_data = await response.json()
                elif method == "POST":
                    async with session.post(url, params=params, json=data) as response:
                        response_data = await response.json()
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                if not response.ok:
                    error_msg = response_data.get("error", {}).get(
                        "message", "Unknown error")
                    logger.error(f"Facebook API error: {error_msg}")
                    raise Exception(f"Facebook API error: {error_msg}")

                return response_data

            except aiohttp.ClientError as e:
                logger.error(
                    f"Network error when calling Facebook API: {str(e)}")
                raise Exception(
                    f"Failed to communicate with Facebook: {str(e)}")
            except Exception as e:
                logger.error(
                    f"Unexpected error in Facebook API call: {str(e)}")
                raise

    async def create_post(self, account_id: str, data: Dict[str, Any]) -> str:
        """Create a post on Facebook."""
        try:
            response = await self._make_request(
                method="POST",
                endpoint=f"{account_id}/feed",
                data=data
            )

            # Facebook returns post ID in the format "{account_id}_{post_id}"
            return response["id"]

        except Exception as e:
            logger.error(f"Error creating Facebook post: {str(e)}")
            raise

    async def get_user_info(self, fields: str = "id,name,picture") -> Dict[str, Any]:
        """Get information about the authenticated user."""
        try:
            return await self._make_request(
                method="GET",
                endpoint="me",
                data={"fields": fields}
            )
        except Exception as e:
            logger.error(f"Error getting user info: {str(e)}")
            raise

    async def get_pages(self, fields: str = "id,name,access_token,picture") -> Dict[str, Any]:
        """Get pages managed by the user."""
        try:
            return await self._make_request(
                method="GET",
                endpoint="me/accounts",
                data={"fields": fields}
            )
        except Exception as e:
            logger.error(f"Error getting pages: {str(e)}")
            raise
