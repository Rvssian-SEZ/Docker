defmodule Vdlarr.SlowIndexing.SlowIndexingHelpers do
  @moduledoc """
  Methods for performing slow indexing tasks and managing the indexing process.

  Many of these methods are made to be kickoff or be consumed by workers.
  """

  use Vdlarr.Media.MediaQuery

  require Logger

  alias Vdlarr.Repo
  alias Vdlarr.Media
  alias Vdlarr.Tasks
  alias Vdlarr.Sources
  alias Vdlarr.Sources.Source
  alias Vdlarr.Media.MediaItem
  alias Vdlarr.YtDlp.MediaCollection
  alias Vdlarr.Utils.FilesystemUtils
  alias Vdlarr.Downloading.DownloadingHelpers
  alias Vdlarr.Utils.CronUtils
  alias Vdlarr.SlowIndexing.FileFollowerServer
  alias Vdlarr.Downloading.DownloadOptionBuilder
  alias Vdlarr.SlowIndexing.MediaCollectionIndexingWorker

  alias Vdlarr.YtDlp.Media, as: YtDlpMedia

  @doc """
  Kills old indexing tasks and starts a new task to index the media collection.

  If the source has a cron schedule set (see `Source.cron_scheduled?/1`), the job is
  scheduled for the next matching time per that expression, ignoring `index_frequency_minutes`
  entirely. Otherwise, the job is delayed based on the source's `index_frequency_minutes`
  setting unless one of the following is true:
    - The `force` option is set to true
    - The source has never been indexed before
    - The source has been indexed before, but the last indexing job was more than
      `index_frequency_minutes` ago

  Returns {:ok, %Task{}}
  """
  def kickoff_indexing_task(%Source{} = source, job_args \\ %{}, job_opts \\ []) do
    scheduling_opts = if job_args[:force], do: [schedule_in: 0], else: calculate_scheduling_opts(source)

    Tasks.delete_pending_tasks_for(source, "MediaCollectionIndexingWorker", include_executing: true)

    MediaCollectionIndexingWorker.kickoff_with_task(source, job_args, job_opts ++ scheduling_opts)
  end

  @doc """
  Returns the Oban scheduling opts (`scheduled_at:` or `schedule_in:`) for the next time
  this source's indexing job should run, scheduled fresh from right now (ie: not adjusted
  for time already elapsed since the last run). This is what drives a job rescheduling
  itself after completing a run - see `MediaCollectionIndexingWorker.reschedule_indexing/1`.
  """
  def scheduling_opts_for(%Source{} = source) do
    if Source.cron_scheduled?(source) do
      cron_scheduling_opts(source)
    else
      [schedule_in: source.index_frequency_minutes * 60]
    end
  end

  @doc """
  A helper method to delete all indexing-related tasks for a source.
  Optionally, you can include executing tasks in the deletion process.

  Returns :ok
  """
  def delete_indexing_tasks(%Source{} = source, opts \\ []) do
    include_executing = Keyword.get(opts, :include_executing, false)

    Tasks.delete_pending_tasks_for(source, "MediaCollectionIndexingWorker", include_executing: include_executing)
  end

  @doc """
  Given a media source, creates (indexes) the media by creating media_items for each
  media ID in the source. Afterward, kicks off a download task for each pending media
  item belonging to the source. Returns a list of media items or changesets
  (if the media item couldn't be created).

  Indexing is slow and usually returns a list of all media data at once for record creation.
  To help with this, we use a file follower to watch the file that yt-dlp writes to
  so we can create media items as they come in. This parallelizes the process and adds
  clarity to the user experience. This has a few things to be aware of which are documented
  below in the file watcher setup method.

  Additionally, in the case of a repeat index we create a download archive file that
  contains some media IDs that we've indexed in the past. Note that this archive doesn't
  contain the most recent IDs but rather a subset of IDs that are offset by some amount.
  Practically, this means that we'll re-index a small handful of media that we've recently
  indexed, but this is a good thing since it'll let us pick up on any recent changes to the
  most recent media items.

  We don't create a download archive for playlists (only channels), nor do we create one if
  the indexing was forced by the user.

  NOTE: downloads are only enqueued if the source is set to download media. Downloads are
  also enqueued for ALL pending media items, not just the ones that were indexed in this
  job run. This should ensure that any stragglers are caught if, for some reason, they
  weren't enqueued or somehow got de-queued.

  Available options:
    - `was_forced`: Whether the indexing was forced by the user

  Returns [%MediaItem{} | %Ecto.Changeset{}]
  """
  def index_and_enqueue_download_for_media_items(source, opts \\ [])

  # `:video` sources represent exactly one video and were already given their
  # collection details up front at creation time (see `SingleVideoHelpers`), so
  # there's no channel/playlist to list - we just fetch that one video's metadata
  # directly and create its single MediaItem. No file watcher, no download archive.
  def index_and_enqueue_download_for_media_items(%Source{collection_type: :video} = source, _opts) do
    source = Repo.preload(source, [:media_profile])
    should_use_cookies = Sources.use_cookies?(source, :indexing)

    result =
      case YtDlpMedia.get_media_attributes(source.original_url, [],
             use_cookies: should_use_cookies,
             sleep_interval_context: :indexing
           ) do
        {:ok, media_attrs} ->
          case Media.create_media_item_from_backend_attrs(source, media_attrs) do
            {:ok, media_item} -> [media_item]
            {:error, changeset} -> [changeset]
          end

        err ->
          [err]
      end

    Sources.update_source(source, %{last_indexed_at: DateTime.utc_now()})
    DownloadingHelpers.enqueue_pending_download_tasks(source)

    result
  end

  def index_and_enqueue_download_for_media_items(%Source{} = source, opts) do
    # The media_profile is needed to determine the quality options to _then_ determine a more
    # accurate predicted filepath
    source = Repo.preload(source, [:media_profile])
    # See the method definition below for more info on how file watchers work
    # (important reading if you're not familiar with it)
    result =
      case setup_file_watcher_and_kickoff_indexing(source, opts) do
        {:ok, media_attributes} ->
          # Reload because the source may have been updated during the (long-running) indexing
          # process and important settings like `download_media` may have changed.
          source = Repo.reload!(source)

          Enum.map(media_attributes, fn media_attrs ->
            case Media.create_media_item_from_backend_attrs(source, media_attrs) do
              {:ok, media_item} -> media_item
              {:error, changeset} -> changeset
            end
          end)

        err ->
          # eg: a yt-dlp command failure (bad cookies, corrupted extractor cache, network
          # error, etc). Surface it instead of crashing the job - Oban's own retry/backoff
          # will pick this source back up on its next scheduled attempt.
          Logger.error("#{__MODULE__}: failed to index source #{source.id}: #{inspect(err)}")

          [err]
      end

    Sources.update_source(source, %{last_indexed_at: DateTime.utc_now()})
    DownloadingHelpers.enqueue_pending_download_tasks(source)

    result
  end

  # The file follower is a GenServer that watches a file for new lines and
  # processes them. This works well, but we have to be resilliant to partially-written
  # lines (ie: you should gracefully fail if you can't parse a line).
  #
  # This works in-tandem with the normal (blocking) media indexing behaviour. When
  # the `setup_file_watcher_and_kickoff_indexing` method completes it'll return the
  # FULL result to the caller for parsing. Ideally, every item in the list will have already
  # been processed by the file follower, but if not, the caller handles creation
  # of any media items that were missed/initially failed.
  #
  # It attempts a graceful shutdown of the file follower after the indexing is done,
  # but the FileFollowerServer will also stop itself if it doesn't see any activity
  # for a sufficiently long time.
  defp setup_file_watcher_and_kickoff_indexing(source, opts) do
    was_forced = Keyword.get(opts, :was_forced, false)
    {:ok, pid} = FileFollowerServer.start_link()

    handler = fn filepath -> setup_file_follower_watcher(pid, filepath, source) end
    should_use_cookies = Sources.use_cookies?(source, :indexing)

    command_opts =
      [output: DownloadOptionBuilder.build_output_path_for(source)] ++
        DownloadOptionBuilder.build_quality_options_for(source) ++
        build_download_archive_options(source, was_forced)

    runner_opts = [file_listener_handler: handler, use_cookies: should_use_cookies, sleep_interval_context: :indexing]
    result = MediaCollection.get_media_attributes_for_collection(source.original_url, command_opts, runner_opts)

    FileFollowerServer.stop(pid)

    result
  end

  defp setup_file_follower_watcher(pid, filepath, source) do
    FileFollowerServer.watch_file(pid, filepath, fn line ->
      case Phoenix.json_library().decode(line) do
        {:ok, media_attrs} ->
          Logger.debug("FileFollowerServer Handler: Got media attributes: #{inspect(media_attrs)}")

          media_struct = YtDlpMedia.response_to_struct(media_attrs)
          create_media_item_and_enqueue_download(source, media_struct)

        err ->
          Logger.debug("FileFollowerServer Handler: Error decoding JSON: #{inspect(err)}")

          err
      end
    end)
  end

  defp create_media_item_and_enqueue_download(source, media_attrs) do
    # Reload because the source may have been updated during the (long-running) indexing process
    # and important settings like `download_media` may have changed.
    source = Repo.reload!(source)

    case Media.create_media_item_from_backend_attrs(source, media_attrs) do
      {:ok, %MediaItem{} = media_item} ->
        DownloadingHelpers.kickoff_download_if_pending(media_item)

      {:error, changeset} ->
        changeset
    end
  end

  # Returns the Oban scheduling opts (`schedule_in:` or `scheduled_at:`) for the next
  # indexing run. Cron-scheduled sources always compute a `scheduled_at:` from their
  # cron expression (ignoring `index_frequency_minutes` entirely); everything else keeps
  # the existing "time since last indexed" interval logic.
  defp calculate_scheduling_opts(%Source{last_indexed_at: nil} = source) do
    if Source.cron_scheduled?(source), do: cron_scheduling_opts(source), else: [schedule_in: 0]
  end

  defp calculate_scheduling_opts(%Source{} = source) do
    if Source.cron_scheduled?(source) do
      cron_scheduling_opts(source)
    else
      offset_seconds = DateTime.diff(DateTime.utc_now(), source.last_indexed_at, :second)
      index_frequency_seconds = source.index_frequency_minutes * 60

      [schedule_in: max(0, index_frequency_seconds - offset_seconds)]
    end
  end

  # Falls back to running immediately if the stored cron expression can't be parsed
  # (shouldn't happen in practice since the changeset validates it, but this keeps
  # scheduling from silently breaking if that invariant is ever violated).
  defp cron_scheduling_opts(source) do
    case CronUtils.next_run_at(source.index_cron_schedule) do
      {:ok, next_run_at} -> [scheduled_at: next_run_at]
      {:error, _} -> [schedule_in: 0]
    end
  end

  # The download archive file works in tandem with --break-on-existing to stop
  # yt-dlp once we've hit media items we've already indexed. But we generate
  # this list with a bit of an offset so we do intentionally re-scan some media
  # items to pick up any recent changes (see `get_media_items_for_download_archive`).
  #
  # From there, we format the media IDs in the way that yt-dlp expects (ie: "<extractor> <media_id>")
  # and return the filepath to the caller. `extractor` is nil for records created before that field
  # existed, so we fall back to "youtube" for those (matching this app's original YouTube-only past).
  defp create_download_archive_file(source) do
    tmpfile = FilesystemUtils.generate_metadata_tmpfile(:txt)

    archive_contents =
      source
      |> get_media_items_for_download_archive()
      |> Enum.map_join("\n", fn media_item -> "#{media_item.extractor || "youtube"} #{media_item.media_id}" end)

    case File.write(tmpfile, archive_contents) do
      :ok -> tmpfile
      err -> err
    end
  end

  # Sorting by `uploaded_at` is important because we want to re-index the most recent
  # media items first but there is no guarantee of any correlation between ID and uploaded_at.
  #
  # The offset is important because we want to re-index some media items that we've
  # recently indexed to pick up on any changes. The limit is because we want this mechanism
  # to work even if, for example, the video we were using as a stopping point was deleted.
  # It's not a perfect system, but it should do well enough.
  #
  # The chosen limit and offset are arbitary, independent, and vibes-based. Feel free to
  # tweak as-needed
  defp get_media_items_for_download_archive(source) do
    MediaQuery.new()
    |> where(^MediaQuery.for_source(source))
    |> order_by(desc: :uploaded_at)
    |> limit(50)
    |> offset(20)
    |> Repo.all()
  end

  # The download archive isn't useful for playlists (since those are ordered arbitrarily)
  # or single-video sources (which are indexed exactly once via a different code path
  # entirely - see the `collection_type == :video` clause of
  # `index_and_enqueue_download_for_media_items/2`), and we don't want to use it if the
  # indexing was forced by the user. In other words, only create an archive for channels
  # that are being indexed as part of their regular indexing schedule. The first indexing
  # pass should also not create an archive.
  defp build_download_archive_options(%Source{collection_type: :playlist}, _was_forced), do: []
  defp build_download_archive_options(%Source{collection_type: :video}, _was_forced), do: []
  defp build_download_archive_options(%Source{last_indexed_at: nil}, _was_forced), do: []
  defp build_download_archive_options(_source, true), do: []

  defp build_download_archive_options(source, _was_forced) do
    archive_file = create_download_archive_file(source)

    [:break_on_existing, download_archive: archive_file]
  end
end
