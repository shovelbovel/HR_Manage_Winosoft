{#
  Shared Chart.js setup for the two pages that render the department/
  contract-type charts (dashboard/index.html and ai/summary.html) — kept as
  one include so both stay visually identical instead of drifting the way
  they had (different bar colors, a pie chart with an unrelated palette).

  Color choices follow the project's data-viz skill: the department chart
  is a single-series magnitude comparison (one brand hue, no legend needed);
  the contract-type chart is a part-to-whole/identity comparison (categorical
  colors), so its three hues — brand teal, then two colors from the skill's
  validated default palette — were run through the skill's palette validator
  or wouldn't be used at all.
#}
const FONT_FAMILY = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif";
const INK = "#111827";
const INK_MUTED = "#4b5563";
const GRID = "#e5e7eb";
const TICK_FONT = { family: FONT_FAMILY, size: 12 };

Chart.defaults.font.family = FONT_FAMILY;
Chart.defaults.color = INK_MUTED;

// Draws the value above each bar — only used on the 3-bar contract-type
// chart, never on the department chart, which can have many more bars than
// a label-per-bar stays readable for.
const barValueLabels = {
  id: "barValueLabels",
  afterDatasetsDraw(chart) {
    const { ctx } = chart;
    chart.data.datasets.forEach((dataset, i) => {
      const meta = chart.getDatasetMeta(i);
      meta.data.forEach((bar, index) => {
        const value = dataset.data[index];
        ctx.save();
        ctx.fillStyle = INK;
        ctx.font = `600 12px ${FONT_FAMILY}`;
        ctx.textAlign = "center";
        ctx.textBaseline = "bottom";
        ctx.fillText(value, bar.x, bar.y - 6);
        ctx.restore();
      });
    });
  },
};

const departmentDistribution = {{ snapshot.department_distribution | tojson }};
new Chart(document.getElementById("departmentChart"), {
  type: "bar",
  data: {
    labels: departmentDistribution.map((entry) => entry[0]),
    datasets: [{
      label: "Employés",
      data: departmentDistribution.map((entry) => entry[1]),
      backgroundColor: "#0d9488",
      borderRadius: 4,
      borderSkipped: false,
      maxBarThickness: 40,
    }],
  },
  options: {
    scales: {
      y: {
        beginAtZero: true,
        ticks: { precision: 0, font: TICK_FONT },
        grid: { color: GRID },
        border: { display: false },
      },
      x: {
        ticks: { font: TICK_FONT },
        grid: { display: false },
        border: { color: GRID },
      },
    },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: INK,
        padding: 10,
        cornerRadius: 6,
        displayColors: false,
        titleFont: { family: FONT_FAMILY, weight: "600" },
        bodyFont: { family: FONT_FAMILY },
      },
    },
  },
});

const contractTypeDistribution = {{ snapshot.contract_type_distribution | tojson }};
const CONTRACT_TYPE_COLORS = { CDI: "#0d9488", CDD: "#2a78d6", STAGE: "#eb6834" };
const contractTypeLabels = Object.keys(contractTypeDistribution);
new Chart(document.getElementById("contractTypeChart"), {
  type: "bar",
  data: {
    labels: contractTypeLabels,
    datasets: [{
      label: "Employés",
      data: Object.values(contractTypeDistribution),
      backgroundColor: contractTypeLabels.map((label) => CONTRACT_TYPE_COLORS[label] || "#0d9488"),
      borderRadius: 4,
      borderSkipped: false,
      maxBarThickness: 56,
    }],
  },
  options: {
    layout: { padding: { top: 20 } },
    scales: {
      y: {
        beginAtZero: true,
        ticks: { precision: 0, font: TICK_FONT },
        grid: { color: GRID },
        border: { display: false },
      },
      x: {
        ticks: { font: TICK_FONT },
        grid: { display: false },
        border: { color: GRID },
      },
    },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: INK,
        padding: 10,
        cornerRadius: 6,
        displayColors: false,
        titleFont: { family: FONT_FAMILY, weight: "600" },
        bodyFont: { family: FONT_FAMILY },
      },
    },
  },
  plugins: [barValueLabels],
});
