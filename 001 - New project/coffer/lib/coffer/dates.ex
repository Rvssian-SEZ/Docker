defmodule Coffer.Dates do
  @moduledoc """
  Small date-arithmetic helpers shared by anything that advances a date by a
  recurring cycle (contract renewals, recurring ledger transactions, ...).
  """

  @doc """
  Elixir's `Date` has no month arithmetic — adds `months` to `date`,
  clamping day-of-month overflow to the target month's last valid day
  (e.g. Jan 31 + 1 month = Feb 28/29, never an invalid "Feb 31").
  """
  def add_months(%Date{} = date, months) when is_integer(months) do
    total_months = date.year * 12 + (date.month - 1) + months
    year = div(total_months, 12)
    month = rem(total_months, 12) + 1
    last_day = Date.new!(year, month, 1) |> Date.days_in_month()
    Date.new!(year, month, min(date.day, last_day))
  end
end
