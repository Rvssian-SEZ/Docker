defmodule Vdlarr.Utils.VersionUtilsTest do
  use ExUnit.Case, async: true

  alias Vdlarr.Utils.VersionUtils

  describe "compare/2" do
    test "returns :eq for identical versions" do
      assert VersionUtils.compare("2025.07.01", "2025.07.01") == :eq
    end

    test "treats missing trailing components as zero" do
      assert VersionUtils.compare("2025.07.01", "2025.07.01.0") == :eq
    end

    test "returns :lt when the left version is older" do
      assert VersionUtils.compare("2025.07.01", "2025.07.02") == :lt
    end

    test "returns :gt when the left version is newer" do
      assert VersionUtils.compare("2025.07.02", "2025.07.01") == :gt
    end

    test "a same-day nightly sorts after that day's stable release" do
      assert VersionUtils.compare("2025.07.01", "2025.07.01.123456") == :lt
      assert VersionUtils.compare("2025.07.01.123456", "2025.07.01") == :gt
    end
  end
end
