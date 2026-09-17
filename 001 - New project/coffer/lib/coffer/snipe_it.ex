defmodule Coffer.SnipeIt do
  @moduledoc """
  Pulls asset (hardware) and consumable data from Snipe-IT into Coffer's
  Inventory module. One-way: Snipe-IT is the source of truth for synced
  items (`source: :snipeit`, matched on `external_id` across re-syncs) —
  Coffer doesn't push anything back. Triggered manually via the Inventory
  page's "Sync from Snipe-IT" button rather than a background job, so a
  mis-pointed `SNIPEIT_URL` doesn't silently spam-create rows on a schedule
  before anyone notices.

  Quantity changes on existing `:consumable` items go through
  `Coffer.Inventory`'s normal issue/adjust functions (not a raw field
  write), so every sync-driven stock change still lands in
  `inventory_transactions` and the audit log exactly like a manually
  recorded one. `:checkoutable` items (Snipe-IT hardware, one Coffer item
  per asset) always sync at `quantity_on_hand: 1` and never move.
  """

  require Logger

  alias Coffer.Inventory
  alias Coffer.Inventory.Item
  alias Coffer.SnipeIt.Client

  defmodule Result do
    @moduledoc "Summary counts returned by `sync_inventory/1`."
    defstruct created: 0, updated: 0, unchanged: 0, errors: []
  end

  def sync_inventory(actor) do
    with {:ok, hardware} <- Client.list_all_hardware(),
         {:ok, consumables} <- Client.list_all_consumables() do
      rows = Enum.map(hardware, &map_hardware/1) ++ Enum.map(consumables, &map_consumable/1)
      {:ok, Enum.reduce(rows, %Result{}, &sync_row(&1, actor, &2))}
    end
  end

  defp sync_row(row, actor, acc) do
    case Inventory.get_item_by_external_id(row.external_id) do
      nil -> create_row(row, actor, acc)
      %Item{} = item -> update_row(item, row, actor, acc)
    end
  end

  defp create_row(row, actor, acc) do
    case Inventory.sync_create_item(row, actor) do
      {:ok, _item} -> %{acc | created: acc.created + 1}
      {:error, changeset} -> add_error(acc, row.external_id, changeset)
    end
  end

  defp update_row(item, row, actor, acc) do
    attrs = Map.drop(row, [:quantity_on_hand, :source, :external_id])

    with {:ok, field_updated} <- Inventory.sync_update_item(item, attrs, actor),
         {:ok, qty_updated} <- sync_quantity(field_updated, row.quantity_on_hand, actor) do
      if field_updated == item and qty_updated == field_updated do
        %{acc | unchanged: acc.unchanged + 1}
      else
        %{acc | updated: acc.updated + 1}
      end
    else
      {:error, changeset} -> add_error(acc, row.external_id, changeset)
    end
  end

  defp add_error(acc, external_id, changeset) do
    Logger.warning("Snipe-IT sync: failed to sync #{external_id}: #{inspect(changeset.errors)}")
    %{acc | errors: [{external_id, changeset} | acc.errors]}
  end

  # Hardware (checkoutable) is always qty 1, one Coffer item per Snipe-IT
  # asset — it never moves via a transaction.
  defp sync_quantity(%Item{tracking_type: :checkoutable} = item, _new_qty, _actor),
    do: {:ok, item}

  defp sync_quantity(%Item{quantity_on_hand: same} = item, same, _actor), do: {:ok, item}

  defp sync_quantity(%Item{} = item, new_qty, actor) when new_qty > item.quantity_on_hand do
    with {:ok, _txn} <-
           Inventory.adjust_stock(
             item,
             %{
               "quantity" => new_qty - item.quantity_on_hand,
               "date" => Date.utc_today(),
               "notes" => "Synced from Snipe-IT"
             },
             actor
           ) do
      {:ok, Inventory.get_item!(item.id)}
    end
  end

  defp sync_quantity(%Item{} = item, new_qty, actor) do
    with {:ok, _txn} <-
           Inventory.issue_stock(
             item,
             %{
               "quantity" => item.quantity_on_hand - new_qty,
               "date" => Date.utc_today(),
               "issued_to" => "Snipe-IT sync",
               "notes" => "Quantity corrected from Snipe-IT"
             },
             actor
           ) do
      {:ok, Inventory.get_item!(item.id)}
    end
  end

  defp map_hardware(row) do
    name =
      case row["name"] do
        n when is_binary(n) and n != "" -> n
        _ -> "#{get_in(row, ["model", "name"]) || "Unknown model"} (#{row["asset_tag"]})"
      end

    %{
      name: name,
      description: get_in(row, ["status", "name"]) || get_in(row, ["status_label", "name"]),
      tracking_type: :checkoutable,
      category: get_in(row, ["category", "name"]),
      location: get_in(row, ["location", "name"]),
      quantity_on_hand: 1,
      unit_cost: parse_cost(row["purchase_cost"]),
      source: :snipeit,
      external_id: "hardware:#{row["id"]}",
      external_updated_at: parse_datetime(get_in(row, ["updated_at", "datetime"])),
      assigned_to: format_assignee(row["assigned_to"])
    }
  end

  # Snipe-IT can assign hardware to a user, another asset, or a location
  # (polymorphic — `type` says which). Only a user assignment is really
  # "who it's assigned to"; the others get a type suffix for clarity.
  defp format_assignee(nil), do: nil
  defp format_assignee(%{"type" => "user", "name" => name}), do: name
  defp format_assignee(%{"type" => type, "name" => name}), do: "#{name} (#{type})"
  defp format_assignee(_), do: nil

  defp map_consumable(row) do
    %{
      name: row["name"],
      tracking_type: :consumable,
      category: get_in(row, ["category", "name"]),
      location: get_in(row, ["location", "name"]),
      quantity_on_hand: row["remaining"] || 0,
      reorder_threshold: row["min_amt"],
      unit_cost: parse_cost(row["purchase_cost"]),
      source: :snipeit,
      external_id: "consumable:#{row["id"]}",
      external_updated_at: parse_datetime(get_in(row, ["updated_at", "datetime"]))
    }
  end

  defp parse_cost(nil), do: nil
  defp parse_cost(cost) when is_number(cost), do: Decimal.from_float(cost * 1.0)

  defp parse_cost(cost) when is_binary(cost) do
    case Decimal.parse(cost) do
      {decimal, _rest} -> decimal
      :error -> nil
    end
  end

  defp parse_datetime(nil), do: nil

  defp parse_datetime(str) do
    # Snipe-IT sends "YYYY-MM-DD HH:MM:SS" (space, not the "T" strict
    # ISO8601 requires) — informational field only, so a parse miss just
    # falls back to nil rather than failing the sync.
    case str |> String.replace(" ", "T", global: false) |> NaiveDateTime.from_iso8601() do
      {:ok, naive} -> DateTime.from_naive!(naive, "Etc/UTC")
      {:error, _} -> nil
    end
  end
end
