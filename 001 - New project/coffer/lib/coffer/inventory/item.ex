defmodule Coffer.Inventory.Item do
  use Coffer.Schema
  import Ecto.Changeset

  @tracking_types [:consumable, :checkoutable]

  schema "inventory_items" do
    field :name, :string
    field :description, :string
    field :tracking_type, Ecto.Enum, values: @tracking_types
    field :category, :string
    field :quantity_on_hand, :integer, default: 0
    field :reorder_threshold, :integer
    field :unit_cost, :decimal
    field :location, :string
    field :active, :boolean, default: true

    belongs_to :created_by, Coffer.Accounts.User

    timestamps(type: :utc_datetime)
  end

  def tracking_types, do: @tracking_types

  @doc """
  For EDITS only — `quantity_on_hand` is deliberately not castable here,
  it only ever changes via `Coffer.Inventory`'s issue/receive/adjust
  functions (which update it atomically alongside the `inventory_transactions`
  row that justifies the change) or a checkout's own lifecycle, so an item
  edit can't silently corrupt the stock count outside that audit trail. Use
  `create_changeset/2` when first adding an item, which does allow setting a
  starting count.
  """
  def changeset(item, attrs) do
    item
    |> cast(attrs, [
      :name,
      :description,
      :tracking_type,
      :category,
      :reorder_threshold,
      :unit_cost,
      :location,
      :active
    ])
    |> validate_required([:name, :tracking_type])
    |> validate_number(:reorder_threshold, greater_than_or_equal_to: 0)
    |> validate_number(:unit_cost, greater_than_or_equal_to: 0)
  end

  @doc "For creating a new item — additionally allows setting the starting `quantity_on_hand`."
  def create_changeset(item, attrs) do
    item
    |> changeset(attrs)
    |> cast(attrs, [:quantity_on_hand])
    |> validate_number(:quantity_on_hand, greater_than_or_equal_to: 0)
  end

  @doc "Only used internally by `Coffer.Inventory` to write the new on-hand quantity."
  def quantity_changeset(item, quantity_on_hand) do
    item
    |> cast(%{quantity_on_hand: quantity_on_hand}, [:quantity_on_hand])
    |> validate_number(:quantity_on_hand, greater_than_or_equal_to: 0)
  end
end
