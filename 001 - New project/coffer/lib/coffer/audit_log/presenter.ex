defmodule Coffer.AuditLog.Presenter do
  @moduledoc """
  Pure formatting helpers that turn a raw `Coffer.AuditLog.Entry` — whose
  `before`/`after` are flat maps of raw field names to raw stored scalars,
  set by each context's private `serialize/1` (see e.g. `Coffer.Ledger`) —
  into human-readable text for the audit log page. No DB access here: the
  LiveView resolves the small reference tables (currencies, vendors,
  envelopes, categories, contracts, users) once into `ref_lookup` and
  passes it in, so this module stays a plain, easily-testable formatter.
  """

  @resource_labels %{
    "LedgerTransaction" => "Ledger transaction",
    "BudgetEnvelope" => "Budget envelope",
    "BudgetCategory" => "Budget category",
    "InventoryItem" => "Inventory item",
    "InventoryTransaction" => "Inventory transaction",
    "ContractAttachment" => "Contract attachment",
    "RoleMapping" => "Role mapping",
    "ExchangeRate" => "Exchange rate"
  }

  def resource_type_label(type), do: Map.get(@resource_labels, type, type)

  def action_label(:create), do: "created"
  def action_label(:update), do: "updated"
  def action_label(:delete), do: "deleted"

  def action_badge_class(:create), do: "badge-success"
  def action_badge_class(:update), do: "badge-info"
  def action_badge_class(:delete), do: "badge-error"

  @display_fields ~w(description name)

  @doc """
  The best human label for the audited record itself, e.g. a transaction's
  description or a vendor's name — pulled from whichever snapshot exists.
  """
  def resource_label(before, after_) do
    source = after_ || before || %{}
    Enum.find_value(@display_fields, &Map.get(source, &1))
  end

  @ignored_fields ~w(id inserted_at updated_at)

  @doc """
  Field-by-field changes for one entry, already formatted for display.

  - `:update` returns `{label, old, new}` triples for fields that changed.
  - `:create`/`:delete` return `{label, value}` pairs for the full snapshot.
  """
  def changes(:update, before, after_, ref_lookup) do
    before = before || %{}
    after_ = after_ || %{}

    (Map.keys(before) ++ Map.keys(after_))
    |> Enum.uniq()
    |> Enum.reject(&(&1 in @ignored_fields))
    |> Enum.filter(fn key -> Map.get(before, key) != Map.get(after_, key) end)
    |> Enum.sort()
    |> Enum.map(fn key ->
      {field_label(key), format_value(key, Map.get(before, key), ref_lookup),
       format_value(key, Map.get(after_, key), ref_lookup)}
    end)
  end

  def changes(action, before, after_, ref_lookup) when action in [:create, :delete] do
    source = after_ || before || %{}

    source
    |> Map.drop(@ignored_fields)
    |> Enum.sort()
    |> Enum.map(fn {key, value} -> {field_label(key), format_value(key, value, ref_lookup)} end)
  end

  def field_label(key) do
    key
    |> to_string()
    |> String.trim_trailing("_id")
    |> String.replace("_", " ")
    |> then(&(String.upcase(String.slice(&1, 0, 1)) <> String.slice(&1, 1..-1//1)))
  end

  @money_fields ~w(amount amount_base)

  def format_value(_field, nil, _ref_lookup), do: "—"
  def format_value(_field, value, _ref_lookup) when value == %{}, do: "—"

  # Nested map fields (e.g. Vendor's `contact_info: %{"email" => ...}`) —
  # never an `_id` reference, those are always scalars.
  def format_value(_field, %{} = value, _ref_lookup) do
    Enum.map_join(value, ", ", fn {k, v} -> "#{field_label(k)}: #{v}" end)
  end

  def format_value(field, value, ref_lookup) do
    cond do
      String.ends_with?(field, "_id") -> resolve_ref(field, value, ref_lookup)
      field in @money_fields -> Coffer.Money.format_string(value)
      is_boolean(value) -> if value, do: "Yes", else: "No"
      true -> value |> to_string() |> humanize_atom_like()
    end
  end

  defp resolve_ref(field, id, ref_lookup) do
    case ref_lookup[field] do
      nil -> "##{id}"
      table -> Map.get(table, id, "##{id}")
    end
  end

  defp humanize_atom_like(str) do
    case String.replace(str, "_", " ") do
      "" -> ""
      replaced -> String.upcase(String.slice(replaced, 0, 1)) <> String.slice(replaced, 1..-1//1)
    end
  end
end
