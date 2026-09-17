defmodule Coffer.Inventory.CheckoutOverdueWorker do
  @moduledoc """
  Daily job (spec §6): flags any `checkouts` row still `:out` with a
  `due_back_at` in the past, firing a `:checkout_overdue` notification.
  Idempotent for free — once flipped to `:overdue`, `list_open_checkouts/0`
  still returns it (not checked in yet) but the `status == :out` filter
  below excludes it, so re-runs never re-notify the same checkout.
  """

  use Oban.Worker, queue: :default, max_attempts: 3

  alias Coffer.Inventory
  alias Coffer.Notifications

  @impl Oban.Worker
  def perform(%Oban.Job{}) do
    now = DateTime.utc_now()

    Inventory.list_open_checkouts()
    |> Enum.filter(fn c ->
      (c.status == :out and c.due_back_at) && DateTime.compare(c.due_back_at, now) == :lt
    end)
    |> Enum.each(&flag_overdue/1)

    :ok
  end

  defp flag_overdue(checkout) do
    {:ok, _updated} = Inventory.system_mark_overdue(checkout)

    Notifications.create(%{
      user_id: nil,
      type: :checkout_overdue,
      message:
        "#{checkout.inventory_item.name} checked out to #{checkout.checked_out_to} is overdue.",
      link: "/inventory/#{checkout.inventory_item_id}/edit"
    })
  end
end
