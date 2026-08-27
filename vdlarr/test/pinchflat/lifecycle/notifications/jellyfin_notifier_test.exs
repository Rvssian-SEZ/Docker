defmodule Pinchflat.Lifecycle.Notifications.JellyfinNotifierTest do
  use Pinchflat.DataCase

  import Pinchflat.MediaFixtures

  alias Pinchflat.Settings
  alias Pinchflat.Lifecycle.Notifications.JellyfinNotifier

  setup do
    on_exit(fn ->
      Settings.set(jellyfin_url: nil)
      Settings.set(jellyfin_api_key: nil)
      Settings.set(jellyfin_path_prefix: nil)
    end)

    :ok
  end

  describe "notify_new_media/1" do
    test "does nothing when jellyfin isn't configured" do
      Settings.set(jellyfin_url: nil)
      Settings.set(jellyfin_api_key: nil)

      expect(HTTPClientMock, :post, 0, fn _url, _body, _headers, _opts -> {:ok, ""} end)

      media_item = media_item_fixture(media_filepath: "/downloads/some/file.mp4")

      assert :ok = JellyfinNotifier.notify_new_media(media_item)
    end

    test "does nothing when only the url is set" do
      Settings.set(jellyfin_url: "http://jellyfin.local:8096")
      Settings.set(jellyfin_api_key: nil)

      expect(HTTPClientMock, :post, 0, fn _url, _body, _headers, _opts -> {:ok, ""} end)

      media_item = media_item_fixture(media_filepath: "/downloads/some/file.mp4")

      assert :ok = JellyfinNotifier.notify_new_media(media_item)
    end

    test "posts the expected request when configured" do
      Settings.set(jellyfin_url: "http://jellyfin.local:8096")
      Settings.set(jellyfin_api_key: "abc123")

      media_item = media_item_fixture(media_filepath: "/downloads/some/file.mp4")

      expect(HTTPClientMock, :post, fn url, body, headers, _opts ->
        assert url == "http://jellyfin.local:8096/Library/Media/Updated"
        assert Phoenix.json_library().decode!(body) == %{"Updates" => [%{"Path" => "/downloads/some/file.mp4", "UpdateType" => "Created"}]}
        assert {"authorization", ~s(MediaBrowser Token="abc123")} in headers
        assert {"x-mediabrowser-token", "abc123"} in headers

        {:ok, ""}
      end)

      assert :ok = JellyfinNotifier.notify_new_media(media_item)
    end

    test "strips a trailing slash from the configured url" do
      Settings.set(jellyfin_url: "http://jellyfin.local:8096/")
      Settings.set(jellyfin_api_key: "abc123")

      media_item = media_item_fixture(media_filepath: "/downloads/some/file.mp4")

      expect(HTTPClientMock, :post, fn url, _body, _headers, _opts ->
        assert url == "http://jellyfin.local:8096/Library/Media/Updated"

        {:ok, ""}
      end)

      assert :ok = JellyfinNotifier.notify_new_media(media_item)
    end

    test "remaps the path when a jellyfin_path_prefix is configured" do
      Settings.set(jellyfin_url: "http://jellyfin.local:8096")
      Settings.set(jellyfin_api_key: "abc123")
      Settings.set(jellyfin_path_prefix: "/data/youtube")

      media_directory = Application.get_env(:pinchflat, :media_directory)
      media_item = media_item_fixture(media_filepath: Path.join(media_directory, "some/file.mp4"))

      expect(HTTPClientMock, :post, fn _url, body, _headers, _opts ->
        assert Phoenix.json_library().decode!(body) == %{
                 "Updates" => [%{"Path" => "/data/youtube/some/file.mp4", "UpdateType" => "Created"}]
               }

        {:ok, ""}
      end)

      assert :ok = JellyfinNotifier.notify_new_media(media_item)
    end

    test "does not raise if the request fails" do
      Settings.set(jellyfin_url: "http://jellyfin.local:8096")
      Settings.set(jellyfin_api_key: "abc123")

      media_item = media_item_fixture(media_filepath: "/downloads/some/file.mp4")

      expect(HTTPClientMock, :post, fn _url, _body, _headers, _opts -> {:error, "connection refused"} end)

      assert :ok = JellyfinNotifier.notify_new_media(media_item)
    end
  end

  describe "test_connection/2" do
    test "returns ok on a successful response" do
      expect(HTTPClientMock, :get, fn url, headers, _opts ->
        assert url == "http://jellyfin.local:8096/System/Info"
        assert {"authorization", ~s(MediaBrowser Token="abc123")} in headers

        {:ok, "{}"}
      end)

      assert {:ok, _message} = JellyfinNotifier.test_connection("http://jellyfin.local:8096", "abc123")
    end

    test "returns an error on a failed response" do
      expect(HTTPClientMock, :get, fn _url, _headers, _opts -> {:error, "unauthorized"} end)

      assert {:error, "unauthorized"} = JellyfinNotifier.test_connection("http://jellyfin.local:8096", "bad-key")
    end

    test "returns an error when the url or api key is blank" do
      assert {:error, _} = JellyfinNotifier.test_connection("", "abc123")
      assert {:error, _} = JellyfinNotifier.test_connection("http://jellyfin.local:8096", "")
      assert {:error, _} = JellyfinNotifier.test_connection(nil, nil)
    end
  end
end
