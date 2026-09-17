defmodule CofferWeb.Charts do
  @moduledoc """
  Server-rendered chart components for the dashboard (spec §8) — plain
  CSS-width bars for the two progress/comparison widgets (simplest correct
  choice, no SVG geometry needed for a bar that's just "how full is this"),
  and real inline SVG for the time-series line chart, where a line genuinely
  needs point-to-point geometry. No client JS, no vendored chart library —
  keeps this consistent with the rest of the app being pure server-rendered
  LiveView (spec §8 explicitly leaves this choice open).
  """

  use Phoenix.Component

  import CofferWeb.CoreComponents, only: [format_money: 1]

  @doc """
  A labeled horizontal progress bar for spend-vs-allocated. Turns the error
  color when `value` exceeds `max` (over-budget) instead of clamping past
  100%, since going over budget is the one state that actually needs to be
  visually obvious.
  """
  attr :label, :string, required: true
  attr :value, Decimal, required: true
  attr :max, Decimal, required: true

  def progress_bar(assigns) do
    assigns =
      assigns
      |> assign(:percent, percent_of(assigns.value, assigns.max))
      |> assign(:over?, Decimal.compare(assigns.value, assigns.max) == :gt)

    ~H"""
    <div class="space-y-1">
      <div class="flex items-center justify-between text-sm">
        <span>{@label}</span>
        <span class={@over? && "text-error font-semibold"}>
          {format_money(@value)} / {format_money(@max)}
        </span>
      </div>
      <div class="h-2 w-full overflow-hidden rounded-full bg-base-200">
        <div
          class={["h-full rounded-full", (@over? && "bg-error") || "bg-primary"]}
          style={"width: #{@percent}%"}
        />
      </div>
    </div>
    """
  end

  @doc "A labeled horizontal bar scaled to `max` (the largest value among the set being rendered), for simple magnitude comparison — no over/under concept, unlike `progress_bar/1`."
  attr :label, :string, required: true
  attr :value, Decimal, required: true
  attr :max, Decimal, required: true

  def bar_row(assigns) do
    assigns = assign(assigns, :percent, percent_of(assigns.value, assigns.max))

    ~H"""
    <div class="space-y-1">
      <div class="flex items-center justify-between text-sm">
        <span>{@label}</span>
        <span>{format_money(@value)}</span>
      </div>
      <div class="h-2 w-full overflow-hidden rounded-full bg-base-200">
        <div class="h-full rounded-full bg-primary" style={"width: #{@percent}%"} />
      </div>
    </div>
    """
  end

  @doc """
  Inline SVG line/area chart. `points` is `[{Date.t(), Decimal.t()}, ...]`,
  already chronologically ordered (spec §8: "spend-over-time, monthly
  buckets"). Renders a flat baseline with no points plotted when `points`
  is empty, rather than a broken/divide-by-zero chart.
  """
  attr :points, :list, required: true

  def line_chart(assigns) do
    width = 600
    height = 200
    padding = 32

    values = Enum.map(assigns.points, fn {_date, value} -> Decimal.to_float(value) end)
    max_value = if values == [], do: 1.0, else: Enum.max([Enum.max(values), 0.01])

    coords =
      assigns.points
      |> Enum.with_index()
      |> Enum.map(fn {{date, value}, index} ->
        x =
          if length(assigns.points) <= 1,
            do: padding,
            else: padding + index * (width - 2 * padding) / (length(assigns.points) - 1)

        y = height - padding - Decimal.to_float(value) / max_value * (height - 2 * padding)
        %{x: x, y: y, date: date, value: value}
      end)

    polyline_points = Enum.map_join(coords, " ", fn %{x: x, y: y} -> "#{x},#{y}" end)

    assigns =
      assigns
      |> assign(:width, width)
      |> assign(:height, height)
      |> assign(:coords, coords)
      |> assign(:polyline_points, polyline_points)

    ~H"""
    <svg viewBox={"0 0 #{@width} #{@height}"} class="w-full h-auto">
      <polyline
        :if={@coords != []}
        points={@polyline_points}
        fill="none"
        stroke="currentColor"
        class="text-primary"
        stroke-width="2"
      />
      <g :for={c <- @coords}>
        <circle cx={c.x} cy={c.y} r="3" fill="currentColor" class="text-primary" />
        <text x={c.x} y={@height - 8} text-anchor="middle" class="fill-current text-[8px] opacity-60">
          {Calendar.strftime(c.date, "%b %y")}
        </text>
      </g>
      <text
        :if={@coords == []}
        x={@width / 2}
        y={@height / 2}
        text-anchor="middle"
        class="fill-current text-xs opacity-60"
      >
        No data in range
      </text>
    </svg>
    """
  end

  defp percent_of(value, max) do
    if Decimal.eq?(max, 0) do
      0
    else
      value
      |> Decimal.div(max)
      |> Decimal.mult(100)
      |> Decimal.min(Decimal.new(100))
      |> Decimal.max(Decimal.new(0))
      |> Decimal.to_float()
    end
  end
end
