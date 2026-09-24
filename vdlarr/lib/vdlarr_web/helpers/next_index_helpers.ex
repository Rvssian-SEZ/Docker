defmodule VdlarrWeb.Helpers.NextIndexHelpers do
  @moduledoc """
  "When will this source next be indexed?" labels, shared by the Dashboard and the Channels
  table. The real scheduled indexing job is the source of truth - it already accounts for
  cron schedules, intervals and manual re-index requests - so this reads Oban rather than
  recomputing a schedule.
  """

  import Ecto.Query

  alias Vdlarr.Repo

  @indexing_worker "Vdlarr.SlowIndexing.MediaCollectionIndexingWorker"
  @pending_states ["executing", "available", "scheduled", "retryable"]

  @doc """
  The earliest pending indexing run per source, preferring one that's already executing.

  Returns %{source_id => {state, scheduled_at}}
  """
  def scheduled_runs do
    from(j in Oban.Job,
      where: j.worker == @indexing_worker and j.state in ^@pending_states,
      select: {fragment("json_extract(?, '$.id')", j.args), j.state, j.scheduled_at}
    )
    |> Repo.all()
    |> Enum.reduce(%{}, fn {source_id, state, at}, acc ->
      Map.update(acc, source_id, {state, at}, fn {old_state, old_at} = old ->
        cond do
          old_state == "executing" -> old
          state == "executing" -> {state, at}
          DateTime.compare(at, old_at) == :lt -> {state, at}
          true -> {old_state, old_at}
        end
      end)
    end)
  end

  @doc """
  Label for one source given `scheduled_runs/0`'s result. The boolean says whether it should
  be shown muted (nothing actually scheduled).

  Returns {binary(), boolean()}
  """
  def label(%{id: id, enabled: enabled, index_frequency_minutes: frequency}, runs) do
    case {Map.get(runs, id), enabled, frequency} do
      {{"executing", _}, _, _} -> {"Indexing now", false}
      {_, false, _} -> {"Paused", true}
      {{_state, at}, _, _} -> {local_datetime_label(at), false}
      {nil, _, freq} when is_integer(freq) and freq <= 0 -> {"Once only", true}
      {nil, _, _} -> {"—", true}
    end
  end

  defp local_datetime_label(datetime) do
    datetime
    |> Timex.Timezone.convert(Application.get_env(:vdlarr, :timezone))
    |> Calendar.strftime("%b %d · %H:%M")
  end
end
