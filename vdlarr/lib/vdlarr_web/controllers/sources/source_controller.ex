defmodule VdlarrWeb.Sources.SourceController do
  use VdlarrWeb, :controller
  use Vdlarr.Sources.SourcesQuery

  alias Vdlarr.Repo
  alias Vdlarr.Media
  alias Vdlarr.Tasks
  alias Vdlarr.Tasks.Task
  alias Vdlarr.Sources
  alias Vdlarr.Sources.Source
  alias Vdlarr.Profiles.MediaProfile
  alias Vdlarr.Media.FileSyncingWorker
  alias Vdlarr.Sources.SourceDeletionWorker
  alias Vdlarr.Sources.SingleVideoHelpers
  alias Vdlarr.Sources.SourceImageHelpers
  alias Vdlarr.Downloading.DownloadingHelpers
  alias Vdlarr.SlowIndexing.SlowIndexingHelpers
  alias Vdlarr.Metadata.SourceMetadataStorageWorker
  alias Vdlarr.Metadata.MetadataFileHelpers
  alias Vdlarr.Utils.FilesystemUtils

  # Validated by content-type, not file extension, since that's client-supplied
  # and not trustworthy. Deliberately small and image-only - see upload_poster/2.
  @allowed_poster_content_types %{
    "image/jpeg" => ".jpg",
    "image/png" => ".png",
    "image/webp" => ".webp"
  }

  def index(conn, _params) do
    render(conn, :index)
  end

  def hidden_index(conn, _params) do
    render(conn, :hidden_index)
  end

  @doc """
  Serves the best available poster image for a source, or a 404 if none exists
  (or the image it points to has been deleted from disk). See `SourceImageHelpers`.

  Cacheable: the underlying file only changes when a source is re-indexed with new
  art (or a custom poster is uploaded), so this sets an ETag/Last-Modified derived
  from the file's own mtime and answers conditional requests with 304 - letting the
  browser skip re-downloading the same poster on every page load while still picking
  up a genuinely new image immediately once the file itself changes.
  """
  def poster(conn, %{"source_id" => id}) do
    source = Sources.get_source!(id)

    case SourceImageHelpers.poster_filepath(source) do
      nil ->
        send_resp(conn, 404, "Image not found")

      filepath ->
        serve_cacheable_file(conn, filepath)
    end
  end

  defp serve_cacheable_file(conn, filepath) do
    %{mtime: mtime, size: size} = File.stat!(filepath, time: :posix)
    etag = ~s("#{mtime}-#{size}")

    conn = put_resp_header(conn, "cache-control", "public, max-age=86400, must-revalidate")

    if etag in get_req_header(conn, "if-none-match") do
      send_resp(conn, 304, "")
    else
      conn
      |> put_resp_header("etag", etag)
      |> put_resp_content_type(MIME.from_path(filepath))
      |> send_file(200, filepath)
    end
  end

  @doc """
  Saves a manually-uploaded poster image for a source, taking priority over any
  auto-downloaded poster (see `SourceImageHelpers.poster_filepath/1`) - unlike
  those, this is never touched by the auto-indexing pipeline, so it survives a
  metadata refresh/re-index.
  """
  def upload_poster(conn, %{"source_id" => id, "poster" => %Plug.Upload{} = upload}) do
    source = Sources.get_source!(id)

    case Map.fetch(@allowed_poster_content_types, upload.content_type) do
      {:ok, ext} ->
        filepath = Path.join(MetadataFileHelpers.metadata_directory_for(source), "custom_poster#{ext}")
        FilesystemUtils.cp_p!(upload.path, filepath)
        {:ok, _} = Sources.update_source(source, %{custom_poster_filepath: filepath})

        conn
        |> put_flash(:info, "Poster updated.")
        |> redirect(to: ~p"/sources/#{source}/edit")

      :error ->
        conn
        |> put_flash(:error, "Please upload a JPEG, PNG, or WebP image.")
        |> redirect(to: ~p"/sources/#{source}/edit")
    end
  end

  def upload_poster(conn, %{"source_id" => id}) do
    source = Sources.get_source!(id)

    conn
    |> put_flash(:error, "No file was selected.")
    |> redirect(to: ~p"/sources/#{source}/edit")
  end

  @doc """
  Removes a manually-uploaded poster, falling back to whatever auto-downloaded
  image (if any) `SourceImageHelpers.poster_filepath/1` resolves to next.
  """
  def remove_custom_poster(conn, %{"source_id" => id}) do
    source = Sources.get_source!(id)

    if source.custom_poster_filepath do
      File.rm(source.custom_poster_filepath)
      {:ok, _} = Sources.update_source(source, %{custom_poster_filepath: nil})
    end

    conn
    |> put_flash(:info, "Custom poster removed.")
    |> redirect(to: ~p"/sources/#{source}/edit")
  end

  def new(conn, params) do
    # This lets me preload the settings from another source for more efficient creation
    cs_struct =
      case to_string(params["template_id"]) do
        "" -> %Source{}
        template_id -> Repo.get(Source, template_id) || %Source{}
      end

    render(conn, :new,
      media_profiles: media_profiles(),
      # Most of these don't actually _need_ to be nullified at this point,
      # but if I don't do it now I know it'll bite me
      changeset:
        Sources.change_source(%Source{
          cs_struct
          | id: nil,
            uuid: nil,
            custom_name: nil,
            description: nil,
            collection_name: nil,
            collection_id: nil,
            collection_type: nil,
            original_url: nil,
            marked_for_deletion_at: nil
        })
    )
  end

  def create(conn, %{"source" => source_params}) do
    delay_automatic_download = Map.get(source_params, "delay_automatic_download") == "true"

    case Sources.create_source_from_params(source_params, delay_automatic_download: delay_automatic_download) do
      {:ok, source} ->
        conn
        |> put_flash(:info, "Source created successfully.")
        |> redirect(to: ~p"/sources/#{source}")

      {:error, %Ecto.Changeset{} = changeset} ->
        render(conn, :new, changeset: changeset, media_profiles: media_profiles())
    end
  end

  @doc """
  Renders the form for downloading a single video (as opposed to a whole
  channel or playlist). This creates a `:video`-type Source under the hood -
  see `SingleVideoHelpers` for details.
  """
  def new_video(conn, _params) do
    render(conn, :new_video,
      media_profiles: media_profiles(),
      changeset: Sources.change_source(%Source{})
    )
  end

  def create_video(conn, %{"source" => %{"original_url" => url} = source_params}) do
    case SingleVideoHelpers.create_source(url, source_params) do
      {:ok, source} ->
        conn
        |> put_flash(:info, "Video queued for download.")
        |> redirect(to: ~p"/sources/#{source}")

      {:error, %Ecto.Changeset{} = changeset} ->
        render(conn, :new_video, changeset: changeset, media_profiles: media_profiles())

      error ->
        conn
        |> put_flash(:error, "Could not fetch video details: #{yt_dlp_error_message(error)}")
        |> render(:new_video,
          changeset: Sources.change_source(%Source{}, source_params),
          media_profiles: media_profiles()
        )
    end
  end

  # yt-dlp failures come back as `{:error, reason}` or `{:error, reason, exit_code}`
  # depending on the backend runner - handle both rather than assuming an arity.
  defp yt_dlp_error_message({:error, reason, _exit_code}) when is_binary(reason), do: reason
  defp yt_dlp_error_message({:error, reason}) when is_binary(reason), do: reason
  defp yt_dlp_error_message(_), do: "unknown error"

  def show(conn, %{"id" => id}) do
    source = Repo.preload(Sources.get_source!(id), :media_profile)

    pending_tasks =
      source
      |> Tasks.list_tasks_for(nil, [:executing, :available, :scheduled, :retryable])
      |> Repo.preload(:job)

    render(conn, :show, source: source, pending_tasks: pending_tasks)
  end

  def edit(conn, %{"id" => id}) do
    source = Sources.get_source!(id)
    changeset = Sources.change_source(source)

    render(conn, :edit, source: source, changeset: changeset, media_profiles: media_profiles())
  end

  def update(conn, %{"id" => id, "source" => source_params}) do
    source = Sources.get_source!(id)

    case Sources.update_source_from_params(source, source_params) do
      {:ok, source} ->
        conn
        |> put_flash(:info, "Source updated successfully.")
        |> redirect(to: ~p"/sources/#{source}")

      {:error, %Ecto.Changeset{} = changeset} ->
        render(conn, :edit,
          source: source,
          changeset: changeset,
          media_profiles: media_profiles()
        )
    end
  end

  def delete(conn, %{"id" => id} = params) do
    # This awkward comparison converts the string to a boolean
    delete_files = Map.get(params, "delete_files", "") == "true"
    source = Sources.get_source!(id)

    {:ok, _} = Sources.update_source(source, %{marked_for_deletion_at: DateTime.utc_now()})
    SourceDeletionWorker.kickoff(source, %{delete_files: delete_files})

    conn
    |> put_flash(:info, "Source deletion started. This may take a while to complete.")
    |> redirect(to: ~p"/sources")
  end

  def force_download_pending(conn, %{"source_id" => id}) do
    wrap_forced_action(
      conn,
      id,
      "Forcing download of pending media items.",
      &DownloadingHelpers.enqueue_pending_download_tasks/1
    )
  end

  def force_download_failed(conn, %{"source_id" => id}) do
    wrap_forced_action(
      conn,
      id,
      "Retrying failed media items.",
      &DownloadingHelpers.enqueue_failed_download_tasks/1
    )
  end

  def restore_automatic_downloads(conn, %{"source_id" => id}) do
    source = Sources.get_source!(id)

    case Sources.restore_automatic_downloads(source) do
      {:ok, source} ->
        conn
        |> put_flash(:info, "Automatic downloads restored.")
        |> redirect(to: ~p"/sources/#{source}")

      {:error, %Ecto.Changeset{}} ->
        conn
        |> put_flash(:error, "Could not restore automatic downloads.")
        |> redirect(to: ~p"/sources/#{source}/edit")
    end
  end

  @doc """
  Enables the source and turns downloading back on. A no-op (aside from the flash
  message) if there's nothing pending to download, so this can't be used to silently
  re-enable a source that has no reason to be running.
  """
  def start_all(conn, %{"source_id" => id}) do
    source = Sources.get_source!(id)

    if startable_source?(source) do
      {:ok, source} = Sources.update_source(source, %{enabled: true, download_media: true})

      conn
      |> put_flash(:info, "Source started.")
      |> redirect(to: ~p"/sources/#{source}")
    else
      conn
      |> put_flash(:info, "Nothing to download for this source.")
      |> redirect(to: ~p"/sources/#{source}")
    end
  end

  @doc """
  Turns downloading off and cancels anything currently in progress or queued, but
  leaves the source enabled - indexing keeps running, media just stops downloading
  until Start is used again. See stop_all/2 for fully disabling the source instead.
  """
  def pause_all(conn, %{"source_id" => id}) do
    source = Sources.get_source!(id)

    if active_downloads_for_source?(source) || queued_downloads_for_source?(source) do
      {:ok, source} = Sources.update_source(source, %{download_media: false})
      DownloadingHelpers.dequeue_pending_download_tasks(source, include_executing: true)

      conn
      |> put_flash(:info, "Source downloads paused.")
      |> redirect(to: ~p"/sources/#{source}")
    else
      conn
      |> put_flash(:info, "No active downloads to pause for this source.")
      |> redirect(to: ~p"/sources/#{source}")
    end
  end

  @doc """
  Fully disables the source (stops indexing too, unlike pause_all/2) and cancels
  anything currently downloading or queued.
  """
  def stop_all(conn, %{"source_id" => id}) do
    source = Sources.get_source!(id)

    if active_downloads_for_source?(source) || queued_downloads_for_source?(source) do
      {:ok, source} = Sources.update_source(source, %{enabled: false, download_media: false})
      DownloadingHelpers.dequeue_pending_download_tasks(source, include_executing: true)

      conn
      |> put_flash(:info, "Source stopped.")
      |> redirect(to: ~p"/sources/#{source}")
    else
      conn
      |> put_flash(:info, "Nothing to stop for this source.")
      |> redirect(to: ~p"/sources/#{source}")
    end
  end

  def force_redownload(conn, %{"source_id" => id}) do
    wrap_forced_action(
      conn,
      id,
      "Forcing re-download of downloaded media items.",
      &DownloadingHelpers.kickoff_redownload_for_existing_media/1
    )
  end

  def force_index(conn, %{"source_id" => id}) do
    wrap_forced_action(
      conn,
      id,
      "Index enqueued.",
      &SlowIndexingHelpers.kickoff_indexing_task(&1, %{force: true})
    )
  end

  def force_metadata_refresh(conn, %{"source_id" => id}) do
    wrap_forced_action(
      conn,
      id,
      "Metadata refresh enqueued.",
      &SourceMetadataStorageWorker.kickoff_with_task/1
    )
  end

  def sync_files_on_disk(conn, %{"source_id" => id}) do
    wrap_forced_action(
      conn,
      id,
      "File sync enqueued.",
      &FileSyncingWorker.kickoff_with_task/1
    )
  end

  defp wrap_forced_action(conn, source_id, message, fun) do
    source = Sources.get_source!(source_id)
    fun.(source)

    conn
    |> put_flash(:info, message)
    |> redirect(to: ~p"/sources/#{source}")
  end

  defp startable_source?(source) do
    source
    |> Media.list_pending_media_items_for()
    |> Enum.any?()
  end

  defp active_downloads_for_source?(source), do: count_download_tasks_for_source(source, ["executing"]) > 0

  defp queued_downloads_for_source?(source) do
    count_download_tasks_for_source(source, ["available", "scheduled", "retryable"]) > 0
  end

  # Download tasks are attached to their media_item, not the source directly (see
  # Tasks.list_tasks_for/3), so this can't just filter on tasks.source_id - it has to
  # join through media_items to find everything currently in flight for this source.
  defp count_download_tasks_for_source(source, states) do
    Repo.one(
      from t in Task,
        join: j in assoc(t, :job),
        join: mi in assoc(t, :media_item),
        where: mi.source_id == ^source.id,
        where: fragment("? LIKE ?", j.worker, "%.MediaDownloadWorker"),
        where: j.state in ^states,
        select: count(t.id)
    )
  end

  defp media_profiles do
    MediaProfile
    |> order_by(asc: :name)
    |> Repo.all()
  end
end
