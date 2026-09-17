defmodule Coffer.Budgets.Category do
  use Coffer.Schema
  import Ecto.Changeset

  schema "budget_categories" do
    field :name, :string

    timestamps(type: :utc_datetime)
  end

  def changeset(category, attrs) do
    category
    |> cast(attrs, [:name])
    |> validate_required([:name])
    |> unique_constraint(:name)
  end
end
