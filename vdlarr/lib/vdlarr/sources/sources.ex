defmodule Vdlarr.Sources do
  @moduledoc """
  The Sources context.
  """

  import Ecto.Query, warn: false
  use Vdlarr.Media.MediaQuery

  alias Vdlarr.Repo
  alias Vdlarr.Media
  alias Vdlarr.Tasks
  alias Vdlarr.Sources.Source
  alias Vdlarr.Profiles.MediaProfile
  alias Vdlarr.YtDlp.MediaCollection
  alias Vdlarr.Metadata.SourceMetadata
  alias Vdlarr.Utils.FilesystemUtils
  alias Vdlarr.Downloading.DownloadingHelpers
  alias Vdlarr.SlowIndexing.SlowIndexingHelpers
  alias Vdlarr.Metadata.SourceMetadataStorageWorker

  @doc """
  Returns the relevant output path template for a source.
  Pulls from the source's override if present, otherwise uses the media profile's.

  Returns binary()
  """
  def output_path_template(source) do
    source = Repo.preload(source, :media_profile)
    media_profile = source.media_profile

    source.output_path_template_override || media_profile.output_path_template
  end

  @doc """
  Returns a boolean indicating whether or not cookies should be used for a given operation.

  Returns boolean()
  """
  def use_cookies?(source, operation) when operation in [:indexing, :downloading, :metadata, :error_recovery] do
    case source.cookie_behaviour do
      :disabled -> false
      :all_operations -> true
      :when_needed -> operation in [:indexing, :error_recovery]
    end
  end

  @doc """
  Returns the list of sources. Returns [%Source{}, ...]
  """
  def list_sources do
    Repo.all(Source)
  end

  @doc """
  Returns the list of sources for a media_profile.

  Returns [%Source{}, ...]
  """
  def list_sources_for(%MediaProfile{} = media_profile) do
    Repo.all(from s in Source, where: s.media_profile_id == ^media_profile.id)
  end

  @doc """
  Gets a single source.

  Returns %Source{}. Raises `Ecto.NoResultsError` if the Source does not exist.
  """
  def get_source!(id), do: Repo.get!(Source, id)

  @doc """
  Creates a source. May attempt to pull additional source details from the
  original_url (if provided). Will attempt to start indexing the source's
  media if successfully inserted.

  Runs an initial `change_source` check to ensure most of the source is valid
  before making an expensive API call. Runs it through `Repo.insert` even
  though we know it's going to fail so it picks up any addl. database errors
  and fulfills our return contract.

  You can pass options to control the behavior of the function:
    - `run_post_commit_tasks` (default: true) - If false, the function will not
      enqueue any tasks in `commit_and_handle_tasks`.

  Returns {:ok, %Source{}} | {:error, %Ecto.Changeset{}}
  """
  def create_source(attrs, opts \\ []) do
    case change_source(%Source{}, attrs, :initial) do
      %Ecto.Changeset{valid?: true} ->
        %Source{}
        |> maybe_change_source_from_url(attrs)
        |> maybe_enable_manual_selection(opts)
        |> commit_and_handle_tasks(opts)

      changeset ->
        Repo.insert(changeset)
    end
  end

  @doc """
  Updates a source. May attempt to pull additional source details from the
  original_url (if changed). May attempt to start indexing the source's
  media if the indexing frequency has been changed.

  Existing indexing tasks will be cancelled if the indexing frequency has been
  changed (logic in `SlowIndexingHelpers.kickoff_indexing_task`)

  Runs an initial `change_source` check to ensure most of the source is valid
  before making an expensive API call. Runs it through `Repo.update` even
  though we know it's going to fail so it picks up any addl. database errors
  and fulfills our return contract.

  You can pass options to control the behavior of the function:
    - `run_post_commit_tasks` (default: true) - If false, the function will not
      enqueue any tasks in `commit_and_handle_tasks`.

  Returns {:ok, %Source{}} | {:error, %Ecto.Changeset{}}
  """
  def update_source(%Source{} = source, attrs, opts \\ []) do
    case change_source(source, attrs, :initial) do
      %Ecto.Changeset{valid?: true} ->
        source
        |> maybe_change_source_from_url(attrs)
        |> commit_and_handle_tasks(opts)

      changeset ->
        Repo.update(changeset)
    end
  end

  # Managed internally - either by SourceMetadataStorageWorker's auto-indexing pipeline,
  # or by SourceController's own poster upload/removal actions (both of which call
  # create_source/2 and update_source/3 directly with their own trusted attrs maps, not
  # through the *_from_params/2 wrappers below). Must never be settable from untrusted
  # params: `GET /sources/:id/poster` serves whatever file `poster_filepath`/
  # `custom_poster_filepath` points to, and removing a custom poster calls `File.rm/1` on
  # it, so an attacker-controlled path in either would be an arbitrary file read/delete.
  @internal_only_fields ~w(nfo_filepath poster_filepath custom_poster_filepath fanart_filepath banner_filepath series_directory)

  @doc """
  Like create_source/2, but strips fields that are managed internally (see
  @internal_only_fields) before casting. Use this - never create_source/2 directly -
  for any params that originate from a web request (a controller action or a LiveView
  event), since those aren't limited to whatever fields the corresponding form renders.

  Returns {:ok, %Source{}} | {:error, %Ecto.Changeset{}}
  """
  def create_source_from_params(params, opts \\ []) do
    create_source(Map.drop(params, @internal_only_fields), opts)
  end

  @doc """
  Like update_source/3, but strips fields that are managed internally (see
  @internal_only_fields) before casting. Use this - never update_source/3 directly -
  for any params that originate from a web request. See create_source_from_params/2.

  Returns {:ok, %Source{}} | {:error, %Ecto.Changeset{}}
  """
  def update_source_from_params(%Source{} = source, params, opts \\ []) do
    update_source(source, Map.drop(params, @internal_only_fields), opts)
  end

  @doc """
  Deletes a source, its media items, and its associated tasks (of any state).
  Can optionally delete the source's media files.

  Returns {:ok, %Source{}} | {:error, %Ecto.Changeset{}}
  """
  def delete_source(%Source{} = source, opts \\ []) do
    delete_files = Keyword.get(opts, :delete_files, false)
    Tasks.delete_tasks_for(source)

    MediaQuery.new()
    |> where(^MediaQuery.for_source(source))
    |> Repo.all()
    |> Enum.each(fn media_item ->
      Media.delete_media_item(media_item, delete_files: delete_files)
    end)

    if delete_files do
      delete_source_files(source)
    end

    delete_internal_metadata_files(source)
    Repo.delete(source)
  end

  @doc """
  Returns an `%Ecto.Changeset{}` for tracking source changes.
  """
  def change_source(%Source{} = source, attrs \\ %{}, validation_stage \\ :pre_insert) do
    Source.changeset(source, attrs, validation_stage)
  end

  @doc """
  Restores a manually-selected playlist source (see `selection_mode`) back to normal
  automatic downloads: switches `selection_mode` to `:all`, re-enables `download_media`,
  and clears `prevent_download` on every media item already indexed for the source, then
  enqueues downloads for anything now pending.

  Returns {:ok, %Source{}} | {:error, %Ecto.Changeset{}}
  """
  def restore_automatic_downloads(%Source{} = source) do
    multi =
      Ecto.Multi.new()
      |> Ecto.Multi.update(:source, change_source(source, %{selection_mode: :all, download_media: true}, :initial))
      |> Ecto.Multi.update_all(
        :restore_media_items,
        MediaQuery.new() |> where(^MediaQuery.for_source(source)),
        set: [prevent_download: false]
      )

    case Repo.transaction(multi) do
      {:ok, %{source: source}} ->
        if source.enabled do
          DownloadingHelpers.enqueue_pending_download_tasks(source)
        end

        {:ok, source}

      {:error, :source, %Ecto.Changeset{} = changeset, _changes} ->
        {:error, changeset}
    end
  end

  # NOTE: When operating in the ideal path, this effectively adds an API call
  # to the source creation/update process. Should be used only when needed.
  defp maybe_change_source_from_url(%Source{} = source, attrs) do
    case change_source(source, attrs) do
      # `:video` sources already know their collection details up front (see
      # `SingleVideoHelpers`) - the channel/playlist auto-detection below would
      # otherwise clobber them with an incorrect guess.
      %Ecto.Changeset{changes: %{collection_type: :video}} = changeset ->
        changeset

      %Ecto.Changeset{changes: %{original_url: _}} = changeset ->
        add_source_details_to_changeset(source, changeset)

      changeset ->
        changeset
    end
  end

  # Only applies at creation time, via the `delay_automatic_download` opt (set from the
  # "Delay Automatic Download" toggle on the New Source form) - playlists only, since
  # indexing a channel with this on would just mean nothing downloads until the user finds
  # the source again. See `restore_automatic_downloads/1` for reverting this.
  defp maybe_enable_manual_selection(changeset, opts) do
    if Keyword.get(opts, :delay_automatic_download, false) &&
         Ecto.Changeset.get_field(changeset, :collection_type) == :playlist do
      changeset
      |> Ecto.Changeset.put_change(:selection_mode, :manual)
      |> Ecto.Changeset.put_change(:download_media, false)
    else
      changeset
    end
  end

  defp delete_source_files(source) do
    mapped_struct = Map.from_struct(source)

    Source.filepath_attributes()
    |> Enum.map(fn field -> mapped_struct[field] end)
    |> Enum.filter(&is_binary/1)
    |> Enum.each(&FilesystemUtils.delete_file_and_remove_empty_directories/1)
  end

  defp delete_internal_metadata_files(source) do
    metadata = Repo.preload(source, :metadata).metadata || %SourceMetadata{}
    mapped_struct = Map.from_struct(metadata)

    SourceMetadata.filepath_attributes()
    |> Enum.map(fn field -> mapped_struct[field] end)
    |> Enum.filter(&is_binary/1)
    |> Enum.each(&FilesystemUtils.delete_file_and_remove_empty_directories/1)
  end

  defp add_source_details_to_changeset(source, changeset) do
    original_url = changeset.changes.original_url
    should_use_cookies = Ecto.Changeset.get_field(changeset, :cookie_behaviour) == :all_operations
    # Skipping sleep interval since this is UI blocking and we want to keep this as fast as possible
    addl_opts = [use_cookies: should_use_cookies, skip_sleep_interval: true]

    case MediaCollection.get_source_details(original_url, [], addl_opts) do
      {:ok, source_details} ->
        add_source_details_by_collection_type(source, changeset, source_details)

      err ->
        runner_error =
          case err do
            {:error, error_msg, _status_code} -> error_msg
            {:error, error_msg} -> error_msg
          end

        Ecto.Changeset.add_error(
          changeset,
          :original_url,
          "could not fetch source details from URL",
          error: runner_error
        )
    end
  end

  defp add_source_details_by_collection_type(source, changeset, source_details) do
    %Ecto.Changeset{changes: changes} = changeset

    collection_changes =
      if source_details.playlist_id == source_details.channel_id do
        %{
          collection_type: :channel,
          collection_id: source_details.channel_id,
          collection_name: source_details.channel_name
        }
      else
        %{
          collection_type: :playlist,
          collection_id: source_details.playlist_id,
          collection_name: source_details.playlist_name
        }
      end

    change_source(source, Map.merge(changes, collection_changes))
  end

  defp commit_and_handle_tasks(changeset, opts) do
    run_post_commit_tasks = Keyword.get(opts, :run_post_commit_tasks, true)

    case Repo.insert_or_update(changeset) do
      {:ok, %Source{} = source} ->
        if run_post_commit_tasks do
          maybe_handle_media_tasks(changeset, source)
          maybe_run_indexing_task(changeset, source)
          maybe_run_metadata_storage_task(changeset, source)
        end

        {:ok, source}

      err ->
        err
    end
  end

  # If the source is new (ie: not persisted), do nothing
  defp maybe_handle_media_tasks(%{data: %{__meta__: %{state: state}}}, _source) when state != :loaded do
    :ok
  end

  # If the source is NOT new (ie: updated),
  # enqueue or dequeue media download tasks as necessary.
  defp maybe_handle_media_tasks(changeset, source) do
    current_changes = changeset.changes
    applied_changes = Ecto.Changeset.apply_changes(changeset)

    # We need both current_changes and applied_changes to determine
    # the course of action to take. For example, we only care if a source is supposed
    # to be `enabled` or not - we don't care if that information comes from the
    # current changes or if that's how it already was in the database.
    # Rephrased, we're essentially using it in place of `get_field/2`
    case {current_changes, applied_changes} do
      {%{download_media: true}, %{enabled: true}} ->
        DownloadingHelpers.enqueue_pending_download_tasks(source)

      {%{enabled: true}, %{download_media: true}} ->
        DownloadingHelpers.enqueue_pending_download_tasks(source)

      {%{download_media: false}, _} ->
        DownloadingHelpers.dequeue_pending_download_tasks(source)

      {%{enabled: false}, _} ->
        DownloadingHelpers.dequeue_pending_download_tasks(source)

      _ ->
        nil
    end

    :ok
  end

  defp maybe_run_indexing_task(changeset, source) do
    case changeset.data do
      # If the changeset is new (not persisted), attempt indexing no matter what
      %{__meta__: %{state: :built}} ->
        SlowIndexingHelpers.kickoff_indexing_task(source)

      # If the record has been persisted, only run indexing if the
      # indexing frequency has been changed and is now greater than 0
      %{__meta__: %{state: :loaded}} ->
        maybe_update_slow_indexing_task(changeset, source)
    end
  end

  defp maybe_run_metadata_storage_task(changeset, source) do
    if Ecto.Changeset.get_field(changeset, :collection_type) == :video do
      # `SourceMetadataStorageWorker` fetches source-level (ie: channel/playlist) metadata
      # like avatar/banner images via yt-dlp's `playlist:` print scope, which never fires
      # for a bare video URL (there's no playlist), so it always fails for `:video` sources.
      # There's no equivalent "series" metadata to fetch for a single video anyway.
      :ok
    else
      do_maybe_run_metadata_storage_task(changeset, source)
    end
  end

  defp do_maybe_run_metadata_storage_task(changeset, source) do
    case {changeset.data, changeset.changes} do
      # If the changeset is new (not persisted), fetch metadata no matter what
      {%{__meta__: %{state: :built}}, _} ->
        SourceMetadataStorageWorker.kickoff_with_task(source)

      # If the record has been persisted, only fetch metadata if the
      # original_url has changed
      {_, %{original_url: _}} ->
        SourceMetadataStorageWorker.kickoff_with_task(source)

      _ ->
        :ok
    end
  end

  defp maybe_update_slow_indexing_task(changeset, source) do
    # See comment in `maybe_handle_media_tasks` as to why we need these
    current_changes = changeset.changes
    applied_changes = Ecto.Changeset.apply_changes(changeset)

    case {current_changes, applied_changes} do
      {%{index_frequency_minutes: mins}, %{enabled: true}} when mins > 0 ->
        SlowIndexingHelpers.kickoff_indexing_task(source)

      {%{enabled: true}, %{index_frequency_minutes: mins}} when mins > 0 ->
        SlowIndexingHelpers.kickoff_indexing_task(source)

      # A cron schedule change (set, cleared, or edited) always needs to reschedule the
      # indexing task, regardless of index_frequency_minutes - without this clause, adding
      # a cron schedule to an existing source (without also touching the frequency dropdown)
      # would silently no-op and leave the old interval-based job running forever.
      {%{index_cron_schedule: _}, %{enabled: true}} ->
        SlowIndexingHelpers.kickoff_indexing_task(source)

      {%{index_cron_schedule: _}, _} ->
        SlowIndexingHelpers.delete_indexing_tasks(source, include_executing: true)

      {%{index_frequency_minutes: _}, _} ->
        SlowIndexingHelpers.delete_indexing_tasks(source, include_executing: true)

      {%{enabled: false}, _} ->
        SlowIndexingHelpers.delete_indexing_tasks(source, include_executing: true)

      _ ->
        :ok
    end
  end
end
