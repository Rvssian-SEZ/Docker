defmodule VdlarrWeb.Sources.SourceScheduleController do
  use VdlarrWeb, :controller

  alias Vdlarr.Repo
  alias Vdlarr.Sources.Source
  alias Vdlarr.Utils.CronUtils

  @preview_count 5

  @doc """
  Live "what will this schedule do" preview for the source form's Schedule control. Uses the
  same cron parsing, timezone handling and interval rule (`last_indexed_at + frequency`) as
  the real scheduler, so the preview can't drift from what actually happens.

  Params: `cron` (blank for interval/once schedules), `frequency` (minutes, -1 for once),
  `source_id` (optional - an existing source's last index time anchors interval previews).
  """
  def preview(conn, params) do
    json(conn, build_preview(params))
  end

  defp build_preview(%{"cron" => cron} = params) when is_binary(cron) and cron != "" do
    if String.trim(cron) == "", do: build_preview(Map.delete(params, "cron")), else: cron_preview(String.trim(cron))
  end

  defp build_preview(params) do
    case parse_int(params["frequency"]) do
      -1 ->
        %{
          ok: true,
          summary: "Indexed once when the source is added, then never again - use Force Index to check for new videos",
          next_runs: []
        }

      minutes when is_integer(minutes) and minutes > 0 ->
        interval_preview(minutes, find_source(params["source_id"]))

      _ ->
        %{ok: false, error: "Pick how often to index"}
    end
  end

  defp cron_preview(cron) do
    case CronUtils.next_run_times(cron, @preview_count) do
      {:ok, times} -> %{ok: true, summary: CronUtils.describe(cron), next_runs: Enum.map(times, &time_label/1)}
      {:error, reason} -> %{ok: false, error: "Invalid cron expression: #{reason}"}
    end
  end

  defp interval_preview(minutes, source) do
    now = DateTime.utc_now()
    base = (source && source.last_indexed_at) || now
    first = DateTime.add(base, minutes * 60, :second)

    next_runs =
      if DateTime.compare(first, now) == :gt do
        Enum.map(0..(@preview_count - 1), &time_label(DateTime.add(first, &1 * minutes * 60, :second)))
      else
        ["Due now" | Enum.map(1..(@preview_count - 1), &time_label(DateTime.add(now, &1 * minutes * 60, :second)))]
      end

    %{
      ok: true,
      summary: "Every #{CronUtils.describe_interval(minutes)}, counted from when the previous index finished",
      # A never-indexed source indexes straight away, then every interval after that
      next_runs:
        if(source && source.last_indexed_at,
          do: next_runs,
          else: ["Right after saving" | Enum.take(next_runs, @preview_count - 1)]
        )
    }
  end

  defp time_label(datetime) do
    datetime
    |> Timex.Timezone.convert(Application.get_env(:vdlarr, :timezone))
    |> Calendar.strftime("%a %d %b · %H:%M")
  end

  defp find_source(id) do
    case parse_int(id) do
      id when is_integer(id) -> Repo.get(Source, id)
      _ -> nil
    end
  end

  defp parse_int(value) when is_integer(value), do: value

  defp parse_int(value) when is_binary(value) do
    case Integer.parse(value) do
      {int, ""} -> int
      _ -> nil
    end
  end

  defp parse_int(_), do: nil
end
