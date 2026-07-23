import { useContext } from "react";
import { PvcContext } from "../../contexts/PvcContext";

export const usePvc = () => {
  const context = useContext(PvcContext);
  if (!context) {
    throw new Error("usePvc must be used within a ECSContext.Provider");
  }
  return context;
};
