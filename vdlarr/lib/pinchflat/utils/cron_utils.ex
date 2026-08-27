defmodule Pinchflat.Utils.CronUtils do
  @moduledoc """
  Helpers for validating cron expressions and computing their next run time.

  Cron expressions are interpreted in the app's configured local timezone
  (`Application.get_env(:pinchflat, :timezone)`, set at boot from the `TZ`/`TIMEZONE`
  env var - see `Pinchflat.Application`) so a schedule like `"0 3 * * *"` means
  3am where the server actually is, not 3am UTC. `Crontab.Scheduler` itself is
  timezone-agnostic (it does calendar math on whatever date struct it's given),
  so the local-time interpretation has to happen around it: get "now" as a naive
  local time, let `crontab` compute the next naive local match, then re-attach
  the local zone and convert to UTC. Oban's `scheduled_at:` requires a `DateTime`
  whose `time_zone` is exactly `"Etc/UTC"` or it raises at insert time, so that
  final conversion isn't optional.

  NOTE: this doesn't attempt to resolve DST-ambiguous or nonexistent local times
  (e.g. a schedule that lands exactly on a "spring forward" gap) - those are rare
  and considered a best-effort edge case for now rather than something worth
  adding complexity to solve up front.
  """

  alias Crontab.CronExpression.Parser

  @doc """
  Returns true if the given string is a valid cron expression, false otherwise.
  """
  def valid?(cron_expression) do
    match?({:ok, _}, Parser.parse(cron_expression))
  end

  @doc """
  Parses a cron expression string. Returns the parser's own (human-readable)
  error message on failure so it can be surfaced directly in a changeset error.

  Returns {:ok, %Crontab.CronExpression{}} | {:error, binary()}
  """
  def parse(cron_expression) do
    Parser.parse(cron_expression)
  end

  @doc """
  Given a valid cron expression string, returns the next time (in UTC) it
  should run, computed relative to now in the app's configured local timezone.

  Returns {:ok, DateTime.t()} | {:error, any()}
  """
  def next_run_at(cron_expression) do
    with {:ok, parsed} <- parse(cron_expression) do
      timezone = Application.get_env(:pinchflat, :timezone)
      local_naive_now = timezone |> Timex.now() |> DateTime.to_naive()

      case Crontab.Scheduler.get_next_run_date(parsed, local_naive_now) do
        {:ok, naive_next_run} ->
          utc_datetime =
            naive_next_run
            |> Timex.to_datetime(timezone)
            |> Timex.Timezone.convert("Etc/UTC")

          {:ok, utc_datetime}

        {:error, _} = err ->
          err
      end
    end
  end

  @doc """
  Best-effort human-readable description of a cron expression. Falls back to
  echoing the raw string for shapes the friendly picker UI doesn't model
  (multi-hour lists, step values, month/day-of-month constraints, etc).

  Returns binary()
  """
  def describe(cron_expression) do
    case parse(cron_expression) do
      {:ok, parsed} -> describe_parsed(parsed, cron_expression)
      {:error, _} -> cron_expression
    end
  end

  @doc """
  Parses a cron expression back into the shape the friendly picker UI
  understands, for prefilling the picker when editing an existing
  cron-scheduled source. Anything that doesn't cleanly match a "daily" or
  "weekly" shape falls back to `mode: "custom"` with the raw string
  preserved, so nothing is ever silently altered.

  Returns %{mode: binary(), hour: integer(), minute: integer(), weekdays: [0..6],
            raw: binary(), summary: binary()}
  """
  def to_picker_state(nil), do: %{mode: "none", hour: 3, minute: 0, weekdays: [], raw: "", summary: ""}
  def to_picker_state(""), do: to_picker_state(nil)

  def to_picker_state(cron_expression) do
    case parse(cron_expression) do
      {:ok, %Crontab.CronExpression{minute: [m], hour: [h], day: [:*], month: [:*], weekday: [:*]}}
      when is_integer(m) and is_integer(h) ->
        %{mode: "daily", hour: h, minute: m, weekdays: [], raw: cron_expression, summary: describe(cron_expression)}

      {:ok, %Crontab.CronExpression{minute: [m], hour: [h], day: [:*], month: [:*], weekday: weekdays}}
      when is_integer(m) and is_integer(h) and is_list(weekdays) and weekdays != [:*] ->
        if Enum.all?(weekdays, &is_integer/1) do
          %{
            mode: "weekly",
            hour: h,
            minute: m,
            weekdays: weekdays,
            raw: cron_expression,
            summary: describe(cron_expression)
          }
        else
          custom_picker_state(cron_expression)
        end

      {:ok, _parsed} ->
        custom_picker_state(cron_expression)

      {:error, _} ->
        custom_picker_state(cron_expression)
    end
  end

  defp custom_picker_state(cron_expression) do
    %{mode: "custom", hour: 3, minute: 0, weekdays: [], raw: cron_expression, summary: describe(cron_expression)}
  end

  defp describe_parsed(
         %Crontab.CronExpression{minute: [m], hour: [h], day: [:*], month: [:*], weekday: [:*]},
         _raw
       )
       when is_integer(m) and is_integer(h) do
    "Runs daily at #{pad(h)}:#{pad(m)}"
  end

  defp describe_parsed(
         %Crontab.CronExpression{minute: [m], hour: [h], day: [:*], month: [:*], weekday: weekdays},
         raw
       )
       when is_integer(m) and is_integer(h) and is_list(weekdays) and weekdays != [:*] do
    if Enum.all?(weekdays, &is_integer/1) do
      "Runs weekly on #{Enum.map_join(weekdays, ", ", &weekday_name/1)} at #{pad(h)}:#{pad(m)}"
    else
      "Custom schedule: #{raw}"
    end
  end

  defp describe_parsed(_parsed, raw), do: "Custom schedule: #{raw}"

  defp pad(n), do: n |> Integer.to_string() |> String.pad_leading(2, "0")

  defp weekday_name(0), do: "Sun"
  defp weekday_name(1), do: "Mon"
  defp weekday_name(2), do: "Tue"
  defp weekday_name(3), do: "Wed"
  defp weekday_name(4), do: "Thu"
  defp weekday_name(5), do: "Fri"
  defp weekday_name(6), do: "Sat"
  defp weekday_name(7), do: "Sun"
  defp weekday_name(other), do: to_string(other)
end
