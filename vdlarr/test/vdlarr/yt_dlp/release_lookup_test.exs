defmodule Vdlarr.YtDlp.ReleaseLookupTest do
  use Vdlarr.DataCase

  alias Vdlarr.YtDlp.ReleaseLookup

  describe "latest_stable_version/0" do
    test "returns the tag name from the GitHub API response" do
      stub(HTTPClientMock, :get, fn _url, _headers -> {:ok, ~s({"tag_name": "2025.06.01"})} end)

      assert {:ok, "2025.06.01"} = ReleaseLookup.latest_stable_version()
    end

    test "returns an error for an unexpected response shape" do
      stub(HTTPClientMock, :get, fn _url, _headers -> {:ok, ~s({"something": "else"})} end)

      assert {:error, :unexpected_response} = ReleaseLookup.latest_stable_version()
    end

    test "passes through the HTTP client's error" do
      stub(HTTPClientMock, :get, fn _url, _headers -> {:error, "network error"} end)

      assert {:error, "network error"} = ReleaseLookup.latest_stable_version()
    end
  end

  describe "version_available?/1" do
    test "returns true when the release lookup succeeds" do
      stub(HTTPClientMock, :get, fn _url, _headers -> {:ok, "{}"} end)

      assert ReleaseLookup.version_available?("2025.06.01")
    end

    test "returns false when the release lookup fails" do
      stub(HTTPClientMock, :get, fn _url, _headers -> {:error, "not found"} end)

      refute ReleaseLookup.version_available?("nonexistent")
    end

    test "returns false for a blank version" do
      refute ReleaseLookup.version_available?("")
      refute ReleaseLookup.version_available?(nil)
    end
  end
end
