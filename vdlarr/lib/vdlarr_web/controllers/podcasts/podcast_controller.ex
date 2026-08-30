defmodule VdlarrWeb.Podcasts.PodcastController do
  use VdlarrWeb, :controller
  use Vdlarr.Media.MediaQuery

  alias Vdlarr.Repo
  alias Vdlarr.Sources.Source
  alias Vdlarr.Media.MediaItem
  alias Vdlarr.Podcasts.RssFeedBuilder
  alias Vdlarr.Podcasts.PodcastHelpers

  def rss_feed(conn, %{"uuid" => uuid}) do
    source = Repo.get_by!(Source, uuid: uuid)
    url_base = url(conn, ~p"/")
    xml = RssFeedBuilder.build(source, limit: 2_000, url_base: url_base)

    conn
    |> put_resp_content_type("application/rss+xml")
    |> put_resp_header("content-disposition", "inline")
    |> send_resp(200, xml)
  end

  def feed_image(conn, %{"uuid" => uuid}) do
    source = Repo.get_by!(Source, uuid: uuid)

    # This is used to fetch a fallback cover image
    # if the source doesn't have any usable images
    media_items =
      MediaQuery.new()
      |> where(^dynamic(^MediaQuery.for_source(source) and ^MediaQuery.downloaded()))
      |> Repo.maybe_limit(1)
      |> Repo.all()

    case PodcastHelpers.select_cover_image(source, media_items) do
      {:error, _} ->
        send_resp(conn, 404, "Image not found")

      {:ok, filepath} ->
        conn
        |> put_resp_content_type(MIME.from_path(filepath))
        |> send_file(200, filepath)
    end
  end

  def episode_image(conn, %{"uuid" => uuid}) do
    media_item = Repo.get_by!(MediaItem, uuid: uuid)

    if media_item.thumbnail_filepath && File.exists?(media_item.thumbnail_filepath) do
      conn
      |> put_resp_content_type(MIME.from_path(media_item.thumbnail_filepath))
      |> send_file(200, media_item.thumbnail_filepath)
    else
      send_resp(conn, 404, "Image not found")
    end
  end
end
