defmodule Coffer.Budgets.Envelope do
  use Coffer.Schema
  import Ecto.Changeset

  schema "budget_envelopes" do
    field :name, :string
    field :description, :string
    field :fiscal_year, :integer
    field :allocated_amount, :decimal
    field :active, :boolean, default: true

    belongs_to :category, Coffer.Budgets.Category
    belongs_to :created_by, Coffer.Accounts.User

    timestamps(type: :utc_datetime)
  end

  @doc """
  User-facing fields only — `created_by_id` is set by `Coffer.Budgets` from
  the authenticated actor, never taken directly from form/API input.
  """
  def changeset(envelope, attrs) do
    envelope
    |> cast(attrs, [:name, :description, :fiscal_year, :allocated_amount, :category_id, :active])
    |> validate_required([:name, :fiscal_year, :allocated_amount, :category_id])
    |> validate_number(:allocated_amount, greater_than_or_equal_to: 0)
    |> foreign_key_constraint(:category_id)
  end
end
