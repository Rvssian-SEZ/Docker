defmodule PinchflatWeb.Settings.SettingHTML do
  use PinchflatWeb, :html

  embed_templates "setting_html/*"

  @doc """
  Renders a setting form.
  """
  attr :conn, Plug.Conn, required: true
  attr :changeset, Ecto.Changeset, required: true
  attr :action, :string, required: true

  def setting_form(assigns)

  def apprise_server_help do
    url = "https://github.com/caronc/apprise/wiki/URLBasics"

    ~s(Server endpoint for Apprise notifications when new media is found. See <a href="#{url}" class="#{help_link_classes()}" target="_blank">Apprise docs</a> for more information)
  end

  @timezone_region_labels %{
    africa: "Africa",
    antarctica: "Antarctica",
    asia: "Asia",
    australasia: "Australia & Pacific",
    etcetera: "UTC & Fixed Offsets",
    europe: "Europe",
    northamerica: "North America",
    southamerica: "South America"
  }

  def timezone_options do
    Tzdata.zone_lists_grouped()
    |> Enum.reject(fn {region, _zones} -> region == :backward end)
    |> Enum.map(fn {region, zones} -> {Map.get(@timezone_region_labels, region, to_string(region)), Enum.sort(zones)} end)
    |> Enum.sort_by(&elem(&1, 0))
  end

  def diagnostic_info_string do
    """
    - App Version: #{Application.spec(:pinchflat)[:vsn]}
    - yt-dlp Version: #{Settings.get!(:yt_dlp_version)}
    - Apprise Version: #{Settings.get!(:apprise_version)}
    - System Architecture: #{to_string(:erlang.system_info(:system_architecture))}
    - Timezone: #{Application.get_env(:pinchflat, :timezone)}
    """
  end

  defp help_link_classes do
    "underline decoration-bodydark decoration-1 hover:decoration-white"
  end
end
