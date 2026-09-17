defmodule Coffer.FiscalYear do
  @moduledoc """
  The financial year is fixed at 1 January - 31 December (spec §2) — no
  configurable FY start in v1. Every FY-boundary calculation in the app goes
  through this module so that assumption is a one-place change if it ever
  needs to become configurable, instead of `~D[year-01-01]` scattered around
  envelope/rollover/reporting code.
  """

  def current_year, do: Date.utc_today().year

  def start_date(year) when is_integer(year), do: Date.new!(year, 1, 1)

  def end_date(year) when is_integer(year), do: Date.new!(year, 12, 31)

  def range(year) when is_integer(year), do: Date.range(start_date(year), end_date(year))
end
