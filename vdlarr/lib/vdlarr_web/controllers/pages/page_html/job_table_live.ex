defmodule Vdlarr.Pages.JobTableLive do
  use VdlarrWeb, :live_view
  use Vdlarr.Tasks.TasksQuery

  alias Vdlarr.Repo
  alias Vdlarr.Tasks
  alias Vdlarr.Tasks.Task
  alias Vdlarr.Downloading.DownloadProgressStore

  def render(%{tasks: []} = assigns) do
    ~H"""
    <div class="flex items-center gap-3 py-2 text-sm text-[#92a1b4]">
      <.material_icon name="check_circle" class="text-m3-green" />
      <p>Nothing Here! No downloads or indexing are running or queued.</p>
    </div>
    """
  end

  def render(assigns) do
    ~H"""
    <div class="space-y-8">
      <section :if={@download_tasks != []} aria-labelledby="activity-downloads">
        <h3 id="activity-downloads" class="mb-3 flex items-center gap-2 text-[15px] font-semibold text-[#edf1f7]">
          <.material_icon name="downloading" /> Downloads
          <span class="text-sm font-normal text-[#7d8da2]">{length(@download_tasks)}</span>
        </h3>
        <div class="max-w-full overflow-x-auto">
          <.table rows={@download_tasks} table_class="text-white">
            <:col :let={task} label="Video" class="max-w-xs truncate">
              <.subtle_link href={task_to_link(task)}>{task_to_record_name(task)}</.subtle_link>
              <div :if={task.media_item} class="truncate text-xs text-[#7d8da2]">{source_name(task)}</div>
            </:col>
            <:col :let={task} label="Status">{status_label(task.job)}</:col>
            <:col :let={task} label="Progress">
              <.download_progress_bar state={@downloads[task.media_item_id]} />
            </:col>
            <:col :let={task} label="When">
              <span class="whitespace-nowrap text-[#b9c7dc]">{when_label(task.job)}</span>
            </:col>
            <:col :let={task} label="" class="flex justify-end">
              <.icon_button
                icon_name="hero-stop-circle"
                tooltip="Stop download"
                phx-click="stop_task"
                phx-value-task_id={task.id}
                data-confirm="Stop this download? Any progress on the current file will be lost."
              />
            </:col>
          </.table>
        </div>
      </section>

      <section :if={@other_tasks != []} aria-labelledby="activity-other">
        <h3 id="activity-other" class="mb-3 flex items-center gap-2 text-[15px] font-semibold text-[#edf1f7]">
          <.material_icon name="sync" /> Indexing &amp; other tasks
          <span class="text-sm font-normal text-[#7d8da2]">{length(@other_tasks)}</span>
        </h3>
        <div class="max-w-full overflow-x-auto">
          <.table rows={@other_tasks} table_class="text-white">
            <:col :let={task} label="Task">{worker_to_task_name(task.job.worker)}</:col>
            <:col :let={task} label="Subject" class="max-w-xs truncate">
              <.subtle_link href={task_to_link(task)}>{task_to_record_name(task)}</.subtle_link>
            </:col>
            <:col :let={task} label="Status">{status_label(task.job)}</:col>
            <:col :let={task} label="When">
              <span class="whitespace-nowrap text-[#b9c7dc]">{when_label(task.job)}</span>
            </:col>
          </.table>
        </div>
      </section>
    </div>
    """
  end

  def mount(_params, _session, socket) do
    VdlarrWeb.Endpoint.subscribe("job:state")
    VdlarrWeb.Endpoint.subscribe("downloads:progress")
    VdlarrWeb.Endpoint.subscribe("downloads:status")

    {:ok, socket |> assign_tasks() |> assign(:downloads, DownloadProgressStore.all())}
  end

  # `Tasks.delete_task/1` cancels the underlying Oban job and removes the Task
  # row. For a job that's already `executing`, Oban's cancellation closes the
  # port's stdin, which `CliUtils.wrap_cmd/4`'s wrapper script watches for
  # specifically to kill the actual yt-dlp OS process - this isn't just a DB
  # flag flip, it stops the real download.
  #
  # Oban's own job-lifecycle telemetry (which `"job:state"` broadcasts ride on)
  # only fires for jobs that actually run to a stop/exception - cancelling a
  # merely-queued (available/scheduled) job never reaches that point, so
  # nothing would otherwise tell every open Activity tab to refresh. Broadcast
  # it ourselves so the row disappears immediately regardless of which state
  # the job was in.
  def handle_event("stop_task", %{"task_id" => task_id}, socket) do
    case Repo.get(Task, task_id) do
      nil ->
        :ok

      task ->
        Tasks.delete_task(task)
        if task.media_item_id, do: DownloadProgressStore.delete(task.media_item_id)
    end

    VdlarrWeb.Endpoint.broadcast("job:state", "change", nil)

    {:noreply, socket}
  end

  def handle_info(%{topic: "job:state", event: "change"}, socket) do
    {:noreply, socket |> assign_tasks() |> assign(:downloads, DownloadProgressStore.all())}
  end

  def handle_info(%{topic: topic, payload: %{media_item_id: id, state: state}}, socket)
      when topic in ["downloads:progress", "downloads:status"] do
    {:noreply, assign(socket, :downloads, Map.put(socket.assigns.downloads, id, state))}
  end

  defp download_task?(%Task{job: %Oban.Job{worker: worker}}) do
    String.ends_with?(worker, "MediaDownloadWorker")
  end

  # Includes not just the currently-executing job but everything still waiting to
  # run, so the Activity tab reflects the whole queue rather than a single row -
  # "retryable" covers a job that failed and is waiting on its backoff to retry.
  @queued_and_running_states ["executing", "available", "scheduled", "retryable"]

  defp get_tasks do
    TasksQuery.new()
    |> TasksQuery.join_job()
    |> where(^TasksQuery.in_state(@queued_and_running_states))
    |> where(^TasksQuery.has_tag("show_in_dashboard"))
    |> order_by([t, j],
      asc: fragment("CASE WHEN ? = 'executing' THEN 0 ELSE 1 END", j.state),
      asc: j.scheduled_at
    )
    |> Repo.all()
    |> Repo.preload([:source, media_item: :source])
  end

  defp assign_tasks(socket) do
    tasks = get_tasks()
    {download_tasks, other_tasks} = Enum.split_with(tasks, &download_task?/1)

    assign(socket, tasks: tasks, download_tasks: download_tasks, other_tasks: other_tasks)
  end

  # Attempt counts only mean something on a retry - "Attempt 0" on a job that simply hasn't
  # run yet was noise
  defp status_label(%Oban.Job{state: "retryable", attempt: attempt}), do: "Retrying (attempt #{attempt + 1})"
  defp status_label(%Oban.Job{state: state}), do: job_state_to_label(state)

  defp when_label(%Oban.Job{state: "executing", attempted_at: at}) when not is_nil(at), do: "Started #{local_time_label(at)}"
  defp when_label(%Oban.Job{state: "available"}), do: "Next when a slot frees up"
  defp when_label(%Oban.Job{state: "retryable", scheduled_at: at}), do: "Retry #{local_time_label(at)}"
  defp when_label(%Oban.Job{scheduled_at: at}) when not is_nil(at), do: local_time_label(at)
  defp when_label(_job), do: ""

  defp local_time_label(datetime) do
    timezone = Application.get_env(:vdlarr, :timezone)
    local = Timex.Timezone.convert(datetime, timezone)
    today = timezone |> Timex.now() |> DateTime.to_date()

    if DateTime.to_date(local) == today,
      do: Calendar.strftime(local, "%H:%M"),
      else: Calendar.strftime(local, "%b %d · %H:%M")
  end

  defp source_name(%Task{media_item: %{source: %{custom_name: name}}}), do: name
  defp source_name(_task), do: ""

  defp job_state_to_label("executing"), do: "Running"
  defp job_state_to_label("available"), do: "Queued"
  defp job_state_to_label("scheduled"), do: "Scheduled"
  defp job_state_to_label("retryable"), do: "Retrying"
  defp job_state_to_label(other), do: other

  defp worker_to_task_name(worker) do
    final_module_part =
      worker
      |> String.split(".")
      |> Enum.at(-1)

    map_worker_to_task_name(final_module_part)
  end

  defp map_worker_to_task_name("MediaDownloadWorker"), do: "Downloading Media"
  defp map_worker_to_task_name("MediaCollectionIndexingWorker"), do: "Indexing Source"
  defp map_worker_to_task_name("MediaQualityUpgradeWorker"), do: "Upgrading Media Quality"
  defp map_worker_to_task_name("SourceMetadataStorageWorker"), do: "Fetching Source Metadata"
  defp map_worker_to_task_name(other), do: other <> " (Report to Devs)"

  defp task_to_record_name(%Task{} = task) do
    case task do
      %Task{source: source} when source != nil -> source.custom_name
      %Task{media_item: mi} when mi != nil -> mi.title
      _ -> "Unknown Record"
    end
  end

  defp task_to_link(%Task{} = task) do
    case task do
      %Task{source: source} when source != nil -> ~p"/sources/#{source.id}"
      %Task{media_item: mi} when mi != nil -> ~p"/sources/#{mi.source_id}/media/#{mi}"
      _ -> "#"
    end
  end
end
