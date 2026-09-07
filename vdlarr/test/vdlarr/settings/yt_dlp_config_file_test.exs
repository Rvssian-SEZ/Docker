defmodule Vdlarr.Settings.YtDlpConfigFileTest do
  use ExUnit.Case, async: false

  alias Vdlarr.Settings.YtDlpConfigFile

  setup do
    on_exit(fn -> YtDlpConfigFile.clear() end)

    :ok
  end

  describe "save/1 and read/0" do
    test "round-trips contents" do
      assert :ok = YtDlpConfigFile.save("--force-ipv4")
      assert YtDlpConfigFile.read() == "--force-ipv4"
    end

    test "rejects contents over the byte limit" do
      too_big = String.duplicate("a", YtDlpConfigFile.max_bytes() + 1)

      assert {:error, :too_large} = YtDlpConfigFile.save(too_big)
    end
  end

  describe "present?/0" do
    test "is false for blank contents" do
      YtDlpConfigFile.save("")

      refute YtDlpConfigFile.present?()
    end

    test "is false for whitespace-only contents" do
      YtDlpConfigFile.save(" \n \n ")

      refute YtDlpConfigFile.present?()
    end

    test "is true once non-blank contents are saved" do
      YtDlpConfigFile.save("--force-ipv4")

      assert YtDlpConfigFile.present?()
    end
  end

  describe "clear/0" do
    test "empties the file without removing it" do
      YtDlpConfigFile.save("--force-ipv4")
      assert :ok = YtDlpConfigFile.clear()

      refute YtDlpConfigFile.present?()
      assert File.exists?(YtDlpConfigFile.filepath())
    end
  end
end
