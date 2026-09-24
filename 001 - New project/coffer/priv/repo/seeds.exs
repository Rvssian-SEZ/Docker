# Script for populating the database. You can run it as:
#
#     mix run priv/repo/seeds.exs
#
# Inside the script, you can read and write to any of your
# repositories directly:
#
#     Coffer.Repo.insert!(%Coffer.SomeSchema{})
#
# We recommend using the bang functions (`insert!`, `update!`
# and so on) as they will fail if something goes wrong.

base_code = Application.fetch_env!(:coffer, :base_currency_code)

Coffer.Repo.insert!(
  %Coffer.Currencies.Currency{
    code: base_code,
    name: "Seychelles Rupee",
    symbol: "₨",
    is_base: true
  },
  on_conflict: :nothing,
  conflict_target: :code
)
