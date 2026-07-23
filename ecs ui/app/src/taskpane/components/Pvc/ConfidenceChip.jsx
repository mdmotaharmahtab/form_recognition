import { Tag } from "antd";

export const CONFIDENCE_LEVELS = {
  High: {
    background: "#dff0d8",
    color: "#2e7d32",
    border: "1px solid #c8e6c9",
  },
  Medium: {
    background: "#fff4e5",
    color: "#e65100",
    border: "1px solid #ffe0b2",
  },
  Low: {
    background: "#fdecea",
    color: "#c62828",
    border: "1px solid #f5c6cb",
  },
};

export const getPVConfidenceLevel = (score) => {
  const value = parseFloat(score ?? 0);

  const percentage =
    value <= 1
      ? Math.round(value * 100)
      : Math.round(value);

  if (percentage >= 75) {
    return "High";
  }

  if (percentage >= 55) {
    return "Medium";
  }

  return "Low";
};

const ConfidenceChip = ({ score }) => {
  const level = getPVConfidenceLevel(score);
  const styles = CONFIDENCE_LEVELS[level];

  return (
    <Tag
      style={{
        ...styles,
        minWidth: 72,
        textAlign: "center",
        fontWeight: 600,
        padding: "2px 4px",
        fontSize: 11,
        marginInlineEnd: 0,
      }}
    >
      {level}
    </Tag>
  );
};

export default ConfidenceChip;