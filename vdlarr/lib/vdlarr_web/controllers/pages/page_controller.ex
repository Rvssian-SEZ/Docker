defmodule VdlarrWeb.Pages.PageController do
  use VdlarrWeb, :controller
  use Vdlarr.Media.MediaQuery

  alias Vdlarr.Repo
  alias Vdlarr.Sources.Source
  alias Vdlarr.Profiles.MediaProfile
  alias Vdlarr.Downloading.DownloadingHelpers

  def home(conn, _params) do
    render_home_page(conn)
  end

  def wanted(conn, _params) do
    render(conn, :wanted)
  end

  def activity(conn, _params) do
    render(conn, :activity)
  end

  @doc """
  Retries every currently-failed media item across every source. Unlike the source-scoped
  `SourceController.force_download_failed/2`, this doesn't check each item's source's
  `download_media` toggle first - matching the existing per-item `force_download` action,
  which has no such guard either.
  """
  def force_download_failed(conn, _params) do
    MediaQuery.new()
    |> where(^dynamic(^MediaQuery.failed()))
    |> Repo.all()
    |> Enum.each(&DownloadingHelpers.retry_download/1)

    conn
    |> put_flash(:info, "Retrying all failed media items.")
    |> redirect(to: ~p"/")
  end

  defp render_home_page(conn) do
    downloaded_media_items = where(MediaQuery.new(), ^MediaQuery.downloaded())

    conn
    |> render(:home,
      media_profile_count: Repo.aggregate(MediaProfile, :count, :id),
      source_count: Repo.aggregate(Source, :count, :id),
      media_item_size: Repo.aggregate(downloaded_media_items, :sum, :media_size_bytes),
      media_item_count: Repo.aggregate(downloaded_media_items, :count, :id)
    )
  end

end
