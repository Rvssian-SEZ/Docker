defmodule Vdlarr.Settings.CookieFile do
  @moduledoc """
  Manages the user-provided `cookies.txt` file that yt-dlp uses to access
  age-restricted, members-only, or otherwise gated content.

  The file lives in `extras/` and is created (blank) on boot by
  `Vdlarr.Boot.PreJobStartupTasks.create_blank_yt_dlp_files/0`.
  `Vdlarr.YtDlp.CommandRunner.add_cookie_file/0` already reads it (when a
  source's `cookie_behaviour` calls for it) - this module is just the
  read/write/validate side so it can be managed from the Settings page
  instead of by SSHing into the container.
  """

  alias Vdlarr.Utils.FilesystemUtils, as: FSUtils

  @filename "cookies.txt"

  @doc """
  Returns the absolute path to the cookies file.
  """
  def filepath do
    Path.join(Application.get_env(:vdlarr, :extras_directory), @filename)
  end

  @doc """
  Returns true if a cookies file exists and has non-whitespace contents.
  """
  def present? do
    FSUtils.exists_and_nonempty?(filepath())
  end

  @doc """
  Replaces the cookies file with the contents at `source_path` (eg: an uploaded
  temp file). Ensures the destination directory exists.

  Returns :ok | {:error, File.posix()}
  """
  def save_from_path(source_path) do
    dest = filepath()
    File.mkdir_p!(Path.dirname(dest))
    File.cp(source_path, dest)
  end

  @doc """
  Clears the cookies file by writing blank contents (rather than deleting it,
  to keep the boot-time invariant that the file exists).

  Returns :ok | {:error, File.posix()}
  """
  def clear do
    File.write(filepath(), "")
  end

  @doc """
  Validates the cookies file _offline_ by parsing it as a Netscape-format
  cookie jar. This deliberately avoids a live network check (a public video
  succeeds even with bad cookies, while an auth-gated check fails for cookies
  only used to bypass bot-detection), so instead it surfaces the failures that
  are actually common: empty, malformed, or fully-expired files.

  Returns:
    - {:ok, %{total: n, active: n, expired: n}}
    - {:error, :empty}
    - {:error, :invalid}
  """
  def validate(now \\ System.system_time(:second)) do
    case File.read(filepath()) do
      {:ok, contents} -> validate_contents(contents, now)
      {:error, _} -> {:error, :empty}
    end
  end

  defp validate_contents(contents, now) do
    if String.trim(contents) == "" do
      {:error, :empty}
    else
      cookies =
        contents
        |> String.split(["\r\n", "\n"])
        |> Enum.map(&parse_line/1)
        |> Enum.reject(&is_nil/1)

      case cookies do
        [] ->
          {:error, :invalid}

        cookies ->
          expired = Enum.count(cookies, fn expiry -> expiry != 0 and expiry < now end)

          {:ok, %{total: length(cookies), active: length(cookies) - expired, expired: expired}}
      end
    end
  end

  # Netscape cookie format: domain \t flag \t path \t secure \t expiry \t name \t value
  # Comment lines start with `#` (except the `#HttpOnly_` domain prefix). Returns the
  # cookie's expiry (integer) for valid lines, otherwise nil.
  defp parse_line(line) do
    cond do
      String.trim(line) == "" -> nil
      String.starts_with?(line, "#") and not String.starts_with?(line, "#HttpOnly_") -> nil
      true -> parse_fields(String.split(line, "\t"))
    end
  end

  defp parse_fields(fields) when length(fields) >= 7 do
    expiry = Enum.at(fields, 4)

    case Integer.parse(String.trim(expiry)) do
      {seconds, _} -> seconds
      :error -> nil
    end
  end

  defp parse_fields(_fields), do: nil
end
