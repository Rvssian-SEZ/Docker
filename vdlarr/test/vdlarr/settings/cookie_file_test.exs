defmodule Vdlarr.Settings.CookieFileTest do
  use ExUnit.Case, async: false

  alias Vdlarr.Settings.CookieFile

  @now 1_000_000_000

  setup do
    on_exit(fn -> CookieFile.clear() end)

    :ok
  end

  defp write_temp_file(contents) do
    path = Path.join(System.tmp_dir!(), "cookie_file_test_#{System.unique_integer([:positive])}.txt")
    File.write!(path, contents)

    on_exit(fn -> File.rm(path) end)

    path
  end

  describe "save_from_path/1 and present?/0" do
    test "copies the source file's contents into place" do
      path = write_temp_file("some cookie contents")

      assert :ok = CookieFile.save_from_path(path)
      assert File.read!(CookieFile.filepath()) == "some cookie contents"
    end

    test "present? is false for blank contents" do
      CookieFile.save_from_path(write_temp_file(""))

      refute CookieFile.present?()
    end

    test "present? is true once non-blank contents are saved" do
      CookieFile.save_from_path(write_temp_file("some cookie contents"))

      assert CookieFile.present?()
    end
  end

  describe "clear/0" do
    test "empties the file without removing it" do
      CookieFile.save_from_path(write_temp_file("some cookie contents"))
      assert :ok = CookieFile.clear()

      refute CookieFile.present?()
      assert File.exists?(CookieFile.filepath())
    end
  end

  describe "validate/1" do
    test "returns :empty for a blank file" do
      CookieFile.clear()

      assert {:error, :empty} = CookieFile.validate(@now)
    end

    test "returns :invalid for content with no valid cookie lines" do
      CookieFile.save_from_path(write_temp_file("this is not a cookies file"))

      assert {:error, :invalid} = CookieFile.validate(@now)
    end

    test "counts active and expired cookies" do
      contents =
        Enum.join(
          [
            "# Netscape HTTP Cookie File",
            ".example.com\tTRUE\t/\tFALSE\t#{@now + 1_000}\tactive_cookie\tvalue",
            ".example.com\tTRUE\t/\tFALSE\t#{@now - 1_000}\texpired_cookie\tvalue",
            "#HttpOnly_.example.com\tTRUE\t/\tTRUE\t0\tsession_cookie\tvalue"
          ],
          "\n"
        )

      CookieFile.save_from_path(write_temp_file(contents))

      assert {:ok, %{total: 3, active: 2, expired: 1}} = CookieFile.validate(@now)
    end

    test "a session cookie (expiry 0) is never counted as expired" do
      contents = ".example.com\tTRUE\t/\tFALSE\t0\tsession_cookie\tvalue"
      CookieFile.save_from_path(write_temp_file(contents))

      assert {:ok, %{total: 1, active: 1, expired: 0}} = CookieFile.validate(@now)
    end

    test "ignores blank lines and regular comment lines" do
      contents =
        Enum.join(
          [
            "# this is a comment",
            "",
            ".example.com\tTRUE\t/\tFALSE\t#{@now + 1_000}\tactive_cookie\tvalue"
          ],
          "\n"
        )

      CookieFile.save_from_path(write_temp_file(contents))

      assert {:ok, %{total: 1, active: 1, expired: 0}} = CookieFile.validate(@now)
    end
  end
end
