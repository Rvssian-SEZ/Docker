defmodule Coffer.Currencies.Currency do
  use Coffer.Schema
  import Ecto.Changeset

  schema "currencies" do
    field :code, :string
    field :name, :string
    field :symbol, :string
    field :is_base, :boolean, default: false

    timestamps(type: :utc_datetime)
  end

  def changeset(currency, attrs) do
    currency
    |> cast(attrs, [:code, :name, :symbol, :is_base])
    |> validate_required([:code, :name, :symbol])
    |> update_change(:code, &String.upcase/1)
    |> unique_constraint(:code)
    |> unique_constraint(:is_base, name: :currencies_single_base_currency_index)
  end
end
