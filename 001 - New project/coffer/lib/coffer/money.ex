defmodule Coffer.Money do
  @moduledoc """
  Shared money-formatting logic. Extracted out of
  `CofferWeb.CoreComponents.format_money/1` so `Coffer.AuditLog.Presenter`
  (business logic, no web-layer dependency) can format audit-log amount
  fields the same way without importing a `CofferWeb` component module.
  """

  @doc """
  Formats a money amount with thousands separators and exactly 2 decimal
  places, e.g. `1000000` -> `"1,000,000.00"`. Display only.
  """
  def format(nil), do: ""

  def format(%Decimal{} = amount) do
    string = amount |> Decimal.round(2) |> Decimal.to_string(:normal)

    {sign, string} =
      case string do
        "-" <> rest -> {"-", rest}
        _ -> {"", string}
      end

    [int_part, decimal_part] = String.split(string, ".")

    grouped_int =
      int_part
      |> String.reverse()
      |> String.replace(~r/(\d{3})(?=\d)/, "\\1,")
      |> String.reverse()

    sign <> grouped_int <> "." <> decimal_part
  end

  @doc "Formats a decimal stored as a string (as audit-log snapshots do)."
  def format_string(nil), do: nil

  def format_string(value) when is_binary(value) do
    case Decimal.parse(value) do
      {decimal, ""} -> format(decimal)
      _ -> value
    end
  end
end
