defmodule PinchflatWeb.Sources.SourceController do
  use PinchflatWeb, :controller
  use Pinchflat.Sources.SourcesQuery

  alias Pinchflat.Repo
  alias Pinchflat.Tasks
  alias Pinchflat.Sources
  alias Pinchflat.Sources.Source
  alias Pinchflat.Profiles.MediaProfile
  alias Pinchflat.Media.FileSyncingWorker
  alias Pinchflat.Sources.SourceDeletionWorker
  alias Pinchflat.Sources.SingleVideoHelpers
  alias Pinchflat.Sources.SourceImageHelpers
  alias Pinchflat.Downloading.DownloadingHelpers
  alias Pinchflat.SlowIndexing.SlowIndexingHelpers
  alias Pinchflat.Metadata.SourceMetadataStorageWorker

  def index(conn, _params) do
    render(conn, :index)
  end

  @doc """
  Serves the best available poster image for a source, or a 404 if none exists
  (or the image it points to has been deleted from disk). See `SourceImageHelpers`.
  """
  def poster(conn, %{"source_id" => id}) do
    source = Sources.get_source!(id)

    case SourceImageHelpers.poster_filepath(source) do
      nil ->
        send_resp(conn, 404, "Image not found")

      filepath ->
        conn
        |> put_resp_content_type(MIME.from_path(filepath))
        |> send_file(200, filepath)
    end
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
    case Sources.create_source(source_params) do
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

    case Sources.update_source(source, source_params) do
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

  defp media_profiles do
    MediaProfile
    |> order_by(asc: :name)
    |> Repo.all()
  end
end
