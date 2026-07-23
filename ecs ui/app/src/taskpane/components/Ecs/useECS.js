import { useContext } from "react";
import { ECSContext } from "../../contexts/ECSContext";

export const useECS = () => {
  const context = useContext(ECSContext);
  if (!context) {
    throw new Error("useECS must be used within a ECSContext.Provider");
  }
  return context;
};
