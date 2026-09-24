defmodule CofferWeb.ExportController do
  use CofferWeb, :controller

  alias Coffer.Authorization.Policy

  alias Coffer.{
    Exports,
    Ledger,
    Contracts,
    Vendors,
    Budgets,
    Currencies,
    Inventory,
    AuditLog,
    Accounts,
    Reporting
  }

  plug :authorize

  defp authorize(conn, _opts) do
    resource = resource_for(conn.path_info)

    if Policy.can?(conn.assigns.current_user, :export, resource) do
      conn
    else
      conn
      |> put_flash(:error, "You're not authorized to export that.")
      |> redirect(to: ~p"/")
      |> halt()
    end
  end

  # `conn.path_info` for e.g. ["ledger", "export.csv"] or ["admin", "audit-log", "export.csv"]
  defp resource_for(["ledger" | _]), do: :ledger_transaction
  defp resource_for(["dashboard" | _]), do: :ledger_transaction
  defp resource_for(["contracts" | _]), do: :contract
  defp resource_for(["vendors" | _]), do: :vendor
  defp resource_for(["budgets" | _]), do: :budget_envelope
  defp resource_for(["admin", "currencies" | _]), do: :currency
  defp resource_for(["inventory", "checkouts" | _]), do: :checkout
  defp resource_for(["inventory" | _]), do: :inventory_item
  defp resource_for(["admin", "audit-log" | _]), do: :audit_log
  defp resource_for(["admin", "role_mappings" | _]), do: :role_mapping

  def ledger_csv(conn, params) do
    filters = if map_size(params) > 0, do: Reporting.parse_filters(params), else: nil
    Exports.stream_ledger_csv(conn, filters)
  end

  def ledger_xlsx(conn, params) do
    filters = if map_size(params) > 0, do: Reporting.parse_filters(params), else: nil

    transactions =
      if filters, do: Reporting.filtered_transactions(filters), else: Ledger.list_transactions()

    send_download(conn, {:binary, Exports.ledger_xlsx(transactions)}, filename: "ledger.xlsx")
  end

  def contracts_csv(conn, _params) do
    send_download(conn, {:binary, Exports.contracts_csv(Contracts.list_contracts())},
      filename: "contracts.csv"
    )
  end

  def vendors_csv(conn, _params) do
    send_download(conn, {:binary, Exports.vendors_csv(Vendors.list_vendors())},
      filename: "vendors.csv"
    )
  end

  def envelopes_csv(conn, _params) do
    send_download(conn, {:binary, Exports.envelopes_csv(Budgets.list_envelopes())},
      filename: "budget_envelopes.csv"
    )
  end

  def currencies_csv(conn, _params) do
    send_download(conn, {:binary, Exports.currencies_csv(Currencies.list_currencies())},
      filename: "currencies.csv"
    )
  end

  def inventory_items_csv(conn, _params) do
    send_download(conn, {:binary, Exports.inventory_items_csv(Inventory.list_items())},
      filename: "inventory_items.csv"
    )
  end

  def checkouts_csv(conn, _params) do
    send_download(conn, {:binary, Exports.checkouts_csv(Inventory.list_all_checkouts())},
      filename: "checkouts.csv"
    )
  end

  def audit_log_csv(conn, _params) do
    send_download(conn, {:binary, Exports.audit_log_csv(AuditLog.list_entries())},
      filename: "audit_log.csv"
    )
  end

  def role_mappings_csv(conn, _params) do
    send_download(conn, {:binary, Exports.role_mappings_csv(Accounts.list_role_mappings())},
      filename: "role_mappings.csv"
    )
  end

  def dashboard_xlsx(conn, params) do
    filters = Reporting.parse_filters(params)
    send_download(conn, {:binary, Exports.dashboard_xlsx(filters)}, filename: "dashboard.xlsx")
  end
end
