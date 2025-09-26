"""Youtube interaction."""

from __future__ import annotations

import os
import pickle
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, cast

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

if TYPE_CHECKING:
    from googleapiclient.discovery import Resource

    from miniatures.models import YTVideo


class YtVideoMetadata:
    """Youtube video metadata."""

    def __init__(
        self, video_id: str, title: str, description: str, date: datetime, status: str
    ):
        """Youtube video metadata."""
        self.video_id = video_id
        self.title = title
        self.description = description
        self.date = date
        self.status = status

    def to_json(self) -> dict[str, Any]:
        """Get the body of the update request."""
        return {
            "id": self.video_id,
            "snippet": {
                "title": self.title,
                "description": self.description,
                "tags": ["jugger", "tournament", "sport"],
                "categoryId": "17",
                "kids": False,  # Specifies if the Video if for kids or not. Defaults to False.
            },
            "status": self._set_status(),
        }

    def _set_status(self) -> dict[str, str]:
        """Site the status of the video."""
        if self.status in ("private", "unlisted"):
            if self.date > datetime.now(self.date.tzinfo):
                return {
                    "privacyStatus": "private",
                    "publishAt": self.date.isoformat(),
                }

        return {}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> YtVideoMetadata:
        """Create a YtVideoMetadata object from a json returned by the API."""
        base_date = (
            data["status"]["publishAt"]
            if "publishAt" in data["status"]
            else data["snippet"]["publishedAt"]
        )

        date_format = "%Y-%m-%dT%H:%M:%S%z"

        fixed_date = datetime.strptime(base_date, date_format).replace(tzinfo=UTC)
        if data["kind"] == "youtube#video":
            video_id = data["id"]
        else:
            video_id = data["snippet"]["resourceId"]["videoId"]
        return YtVideoMetadata(
            video_id=video_id,
            title=data["snippet"]["title"],
            description=data["snippet"]["description"],
            date=fixed_date,
            status=data["status"]["privacyStatus"],
        )

    @classmethod
    def from_ytvideo_model(cls, yt_video: YTVideo) -> YtVideoMetadata:
        """Create a YtVideoMetadata object from a YTVideo model."""
        if yt_video.linked_video is None:
            raise ValueError("YTVideo has no linked video")
        return YtVideoMetadata(
            video_id=yt_video.video_id,
            title=yt_video.linked_video.video_name,
            description=yt_video.linked_video.description,
            status=yt_video.privacy_status,
            date=yt_video.linked_video.publication_date,
        )


class YTInteraction:
    """Youtube interaction. main class"""

    API_NAME = "youtube"
    API_VERSION = "v3"
    """SCOPES = ['https://www.googleapis.com/auth/youtube.force-ssl',
              'https://www.googleapis.com/auth/youtube.upload',
              'https://www.googleapis.com/auth/youtube']"""
    SCOPES: ClassVar[list[str]] = ["https://www.googleapis.com/auth/youtube"]

    CLIENT_SECRET_FILE = Path(os.getenv("CLIENT_SECRET_FILE", ""))
    CHANNEL_ID = str(os.getenv("CHANNEL_ID", ""))  # may not be needed
    # This OAuth 2.0 access scope allows for read-only access to the authenticated
    # user's account, but not other types of account access.

    def __init__(self) -> None:
        """Youtube interaction."""
        self.service = self._create_service()
        if str(self.CLIENT_SECRET_FILE) == "":
            raise ValueError("CLIENT_SECRET_FILE is not set you can set it in .direnv")
        if str(self.CHANNEL_ID) == "":
            raise ValueError("CHANNEL_ID is not set you can set it in .direnv")

    def get_all_videos(
        self, from_date: datetime = datetime(2023, 12, 10, tzinfo=UTC)
    ) -> list[YtVideoMetadata]:
        """Get all videos uploaded to the channel."""
        uploads_playlist = self._get_my_uploads_list()
        if uploads_playlist is None:
            return []
        return self._get_video_list(uploads_playlist, from_date)

    def _create_service(self) -> Resource:
        """Create the service, request google credentials."""
        print(
            self.CLIENT_SECRET_FILE,
            self.API_NAME,
            self.API_VERSION,
            self.SCOPES,
            sep="-",
        )
        if self.CLIENT_SECRET_FILE is None or str(self.CLIENT_SECRET_FILE) == "":
            raise ValueError("CLIENT_SECRET_FILE is not set you can set it in .direnv")
        print("CREDSSS : " + str(self.CLIENT_SECRET_FILE) + "   " + str(self.SCOPES))

        print("[google_authentication] [Create_Service] Scopes : " + str(self.SCOPES))

        cred = None

        pickle_file = Path(f"token_{self.API_NAME}_{self.API_VERSION}.pickle")

        if pickle_file.exists():
            with pickle_file.open("rb") as token:
                cred = pickle.load(token)

        if not cred or not cred.valid:
            if cred and cred.expired and cred.refresh_token:
                cred.refresh(Request())  # type: ignore[no-untyped-call]
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.CLIENT_SECRET_FILE, self.SCOPES
                )
                cred = flow.run_local_server()

            with pickle_file.open("wb") as token:
                pickle.dump(cred, token)

        try:
            service = build(self.API_NAME, self.API_VERSION, credentials=cred)
            print(
                "[google_authentication] [Create_Service] service created successfully - "
                + str(self.API_NAME)
            )
        except Exception as e:
            print("[google_authentication] [Create_Service] Unable to connect.")
            print("[google_authentication] [Create_Service] ERROR : " + str(e))
            raise ValueError("Unable to create service") from e
        else:
            return service

    def _get_my_uploads_list(self) -> dict[str, Any] | None:
        # Retrieve the contentDetails part of the channel resource for the
        # authenticated user's channel.
        request = self.service.channels().list(mine=True, part="contentDetails")  # type: ignore[attr-defined]

        channels_response = request.execute()
        for channel in channels_response["items"]:
            # From the API response, extract the playlist ID that identifies the list
            # of videos uploaded to the authenticated user's channel.
            return cast(
                dict[str, Any], channel["contentDetails"]["relatedPlaylists"]["uploads"]
            )

        return None

    def _get_video_list(
        self, uploads_playlist_id: dict[str, Any], from_date: datetime
    ) -> list[YtVideoMetadata]:
        """Get the list of videos uploaded to the channel.

        Args:
            uploads_playlist_id: id of the uploads playlist
            from_date: date from which to start the search
        return:
            list of videos metadata
        """
        _from_date = from_date.replace(tzinfo=UTC)
        output: list[YtVideoMetadata] = []

        playlist_items_list_request = self.service.playlistItems().list(  # type: ignore[attr-defined]
            playlistId=uploads_playlist_id,
            part="snippet,contentDetails,status",
            maxResults=50,
        )

        print("Videos in list %s" % uploads_playlist_id)
        while playlist_items_list_request:
            playlist_items_list_response = playlist_items_list_request.execute()

            output += [
                YtVideoMetadata.from_json(playlist_item)
                for playlist_item in playlist_items_list_response["items"]
            ]

            playlist_items_list_request = self.service.playlistItems().list_next(  # type: ignore[attr-defined]
                playlist_items_list_request, playlist_items_list_response
            )

        return output

    def get_video(self, video_id: str) -> YtVideoMetadata:
        """Get the video metadata.

        Args:
            video_id: video id
        Returns:
            response of the get request dictionairy with the following keys:
                videoid, title, description, date, status
        """
        item = (
            self.service.videos()  # type: ignore[attr-defined]
            .list(part="snippet,contentDetails,status", id=video_id)
            .execute()
            .items[0]
        )
        return YtVideoMetadata.from_json(item)

    def update_video(self, body: YtVideoMetadata) -> YtVideoMetadata:
        """Update the video metadata.

        Args:
            video_id: video id
            body: body of the update request (see https://developers.google.com/youtube/v3/docs/videos/update)

        Returns:
            response: response of the update request
        """
        request = self.service.videos().update(  # type: ignore[attr-defined]
            part="snippet,contentDetails,status", body=body.to_json()
        )
        response = request.execute()
        return YtVideoMetadata.from_json(response)

    def set_miniature(self, video_id: str, image_file: Path) -> None:
        """Set the thumbnail of the video.

        Args:
            video_id: video id
            image_file: local path to the image file.
        """
        request = self.service.thumbnails().set(  # type: ignore[attr-defined]
            videoId=video_id,
            media_body=MediaFileUpload(image_file),
        )
        request.execute()
