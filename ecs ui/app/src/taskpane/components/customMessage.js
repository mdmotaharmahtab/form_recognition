// utils/customMessage.js
import { notification } from "antd";

const customMessage = {
  error: (content, key = "globalError") => {
    notification.error({
      key,
      message: "Error",
      description: content,
      duration: 0, // stays until user closes
      closable: true, // show X
    });
    return key;
  },
  success: (content, key) => {
    notification.success({
      key,
      message: "Success",
      description: content,
      duration: 3,
    });
  },
  info: (content, key) => {
    notification.info({
      key,
      message: "Info",
      description: content,
      duration: 3,
    });
  },
  destroy: (key) => {
    if (key) notification.destroy(key);
    else notification.destroy();
  },
};

export default customMessage;
