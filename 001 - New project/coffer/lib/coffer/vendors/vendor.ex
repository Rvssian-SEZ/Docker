defmodule Coffer.Vendors.Vendor do
  use Coffer.Schema
  import Ecto.Changeset

  schema "vendors" do
    field :name, :string
    field :contact_info, :map, default: %{}
    field :notes, :string

    timestamps(type: :utc_datetime)
  end

  def changeset(vendor, attrs) do
    vendor
    |> cast(attrs, [:name, :contact_info, :notes])
    |> validate_required([:name])
  end
end
