defmodule Coffer.Currencies.ExchangeRate do
  use Coffer.Schema
  import Ecto.Changeset

  schema "exchange_rates" do
    field :rate_to_base, :decimal
    field :effective_from, :date
    field :effective_to, :date

    belongs_to :currency, Coffer.Currencies.Currency
    belongs_to :created_by, Coffer.Accounts.User

    timestamps(type: :utc_datetime)
  end

  def changeset(exchange_rate, attrs) do
    exchange_rate
    |> cast(attrs, [:rate_to_base, :effective_from, :effective_to, :currency_id, :created_by_id])
    |> validate_required([:rate_to_base, :effective_from, :currency_id])
    |> validate_number(:rate_to_base, greater_than: 0)
    |> foreign_key_constraint(:currency_id)
    |> foreign_key_constraint(:created_by_id)
  end
end
