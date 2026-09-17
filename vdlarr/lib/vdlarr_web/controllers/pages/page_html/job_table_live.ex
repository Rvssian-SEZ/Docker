defmodule Vdlarr.Pages.JobTableLive do
  use VdlarrWeb, :live_view
  use Vdlarr.Tasks.TasksQuery

  alias Vdlarr.Repo
  alias Vdlarr.Tasks.Task
  alias VdlarrWeb.CustomComponents.TextComponents

  def render(%{tasks: []} = assigns) do
    ~H"""
    <div class="mb-4 flex items-center">
      <p>Nothing Here!</p>
    </div>
    """
  end

  def render(assigns) do
    ~H"""
    <div class="max-w-full overflow-x-auto">
      <.table rows={@tasks} table_class="text-white">
        <:col :let={task} label="Task">
          {worker_to_task_name(task.job.worker)}
        </:col>
        <:col :let={task} label="Subject" class="truncate max-w-xs">
          <.subtle_link href={task_to_link(task)}>
            {task_to_record_name(task)}
          </.subtle_link>
        </:col>
        <:col :let={task} label="Status">
          {job_state_to_label(task.job.state)}
        </:col>
        <:col :let={task} label="Progress">
          <.download_progress_bar
            :if={download_task?(task)}
            progress={@progress[task.media_item_id]}
            status_line={@status_lines[task.media_item_id]}
          />
          <span :if={!download_task?(task)}>Attempt {task.job.attempt}</span>
        </:col>
        <:col :let={task} label="Started At">
          {format_datetime(task.job.attempted_at)}
        </:col>
      </.table>
    </div>
    """
  end

  def mount(_params, _session, socket) do
    VdlarrWeb.Endpoint.subscribe("job:state")
    VdlarrWeb.Endpoint.subscribe("downloads:progress")
    VdlarrWeb.Endpoint.subscribe("downloads:status")

    {:ok, assign(socket, tasks: get_tasks(), progress: %{}, status_lines: %{})}
  end

  def handle_info(%{topic: "job:state", event: "change"}, %{assigns: assigns} = socket) do
    tasks = get_tasks()
    visible_ids = MapSet.new(tasks, & &1.media_item_id)

    pruned_progress = Map.filter(assigns.progress, fn {id, _} -> MapSet.member?(visible_ids, id) end)
    pruned_status_lines = Map.filter(assigns.status_lines, fn {id, _} -> MapSet.member?(visible_ids, id) end)

    {:noreply, assign(socket, tasks: tasks, progress: pruned_progress, status_lines: pruned_status_lines)}
  end

  def handle_info(%{topic: "downloads:progress", event: "progress", payload: payload}, socket) do
    progress = Map.put(socket.assigns.progress, payload.media_item_id, payload.progress)

    {:noreply, assign(socket, :progress, progress)}
  end

  def handle_info(%{topic: "downloads:status", event: "status", payload: payload}, socket) do
    status_lines = Map.put(socket.assigns.status_lines, payload.media_item_id, payload.line)

    {:noreply, assign(socket, :status_lines, status_lines)}
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
    |> Repo.preload([:media_item, :source])
  end

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

  defp format_datetime(nil), do: ""

  defp format_datetime(datetime) do
    TextComponents.datetime_in_zone(%{datetime: datetime, format: "%Y-%m-%d %H:%M"})
  end
end
