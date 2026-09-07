defmodule Vdlarr.YtDlp.UnavailableMedia do
  @moduledoc """
  Classifies yt-dlp error output for media that can never be downloaded
  (members-only, private, or removed videos).

  Deliberately kept separate from `MediaDownloadWorker.non_retryable_error?/1`:
  that list only decides whether a job should stop retrying, while this one
  gates the much stronger "ignore unavailable media" setting, which marks the
  item `prevent_download` and clears its error so it drops out of both the
  Pending and Failed tabs entirely. Callers should run this after any
  cookie-retry path - a members-only video may still be downloadable with the
  right cookies.
  """

  @error_strings [
    "Join this channel to get access to members-only content",
    "This video is available to this channel's members",
    "members-only content",
    "Private video",
    "Sign in if you've been granted access to this video",
    "Video unavailable",
    "This video has been removed",
    "This video is no longer available"
  ]

  @doc """
  The list of yt-dlp error substrings indicating permanently unavailable media.
  """
  def error_strings, do: @error_strings

  @doc """
  Returns true if the given yt-dlp error message indicates permanently
  unavailable media.
  """
  def error?(message) do
    String.contains?(to_string(message), @error_strings)
  end

  @doc """
  Returns the first matched unavailable-media substring in the given message,
  or nil if none match. Useful for recording a human-readable reason.
  """
  def matched_reason(message) do
    string = to_string(message)

    Enum.find(@error_strings, fn substring -> String.contains?(string, substring) end)
  end
end
