defmodule Vdlarr.YtDlp.UnavailableMediaTest do
  use ExUnit.Case, async: true

  alias Vdlarr.YtDlp.UnavailableMedia

  describe "error?/1" do
    test "returns true for known permanently-unavailable errors" do
      assert UnavailableMedia.error?("ERROR: Private video")
      assert UnavailableMedia.error?("ERROR: Video unavailable")
      assert UnavailableMedia.error?("This video has been removed by the uploader")

      assert UnavailableMedia.error?(
               "This video is available to this channel's members on level: foo"
             )
    end

    test "returns false for other errors" do
      refute UnavailableMedia.error?("Some transient network error")
    end

    test "returns false for nil" do
      refute UnavailableMedia.error?(nil)
    end
  end

  describe "matched_reason/1" do
    test "returns the matched substring" do
      assert UnavailableMedia.matched_reason("ERROR: Private video") == "Private video"
    end

    test "returns nil when nothing matches" do
      assert UnavailableMedia.matched_reason("Some transient network error") == nil
    end
  end
end
