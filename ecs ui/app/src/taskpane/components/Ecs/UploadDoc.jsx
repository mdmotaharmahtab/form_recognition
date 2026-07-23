import React, { useState } from "react";
import { Button, Flex, Upload, Spin, message, Collapse, Modal } from "antd";
import { DeleteOutlined, InboxOutlined } from "@ant-design/icons";
import styled, { createGlobalStyle } from "styled-components";
import { useECS } from "./useECS";
import { fileToBase64 } from "../../../services";
import IndicationTable from "./IndicationTable";
import "./upload.css";

const GlobalStyle = createGlobalStyle`
  * {
    font-family: 'Open Sans', sans-serif !important;
    .ant-upload-drag-icon svg {
      fill: #426BBA;
    }
    .ant-collapse-expand-icon {
      display: none !important;
    }
    .ant-collapse-header-text {
      color: #426BBA;
      font-weight: 600;
    }
  }
`;

const StyledButton = styled(Button)`
  background: #e3ecff;
  color: #426bba !important;
  font-weight: 600;
  font-size: 14px;
  border: none;
  border-radius: 1rem;
  box-shadow: 0 2px 6px rgba(66, 107, 186, 0.2);
  padding: 4px 16px;

  &:hover {
    background: #d7e4ff !important;
    color: #426bba !important;
  }
`;

const { Dragger } = Upload;
const { Panel } = Collapse;

const UploadDoc = () => {
  const {
    setFileList,
    fileList,
    handleBase64Upload,
    loading,
    setLoading,
    setTip,
    protocolId,
    setProtocolId,
    setIsFileDigitized,
    isFileDigitized,
    indication,
    setIndication
  } = useECS();

  const [activeKeys, setActiveKeys] = useState(["1"]);
  // const hasAnyIndication = indication?.molecule || indication?.indication || indication?.ta;

  const handleUpload = async () => {
    if (!fileList || fileList.length === 0) {
      message.warning("Please select a file to upload.");
      return;
    }
    setLoading(true);
    setTip("File is being uploaded...");
    const file = fileList[0];
    const base64File = await fileToBase64(file);
    handleBase64Upload(base64File);
  };

  const props = {
    multiple: false,
    maxCount: 1, // allow strictly one file
    beforeUpload: (file) => {
      // Restrict file types (only PDF & DOCX)
      const allowedTypes = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      ];
      const allowedExtensions = [".pdf", ".docx"];

      const fileExt = file.name
        .slice(file.name.lastIndexOf("."))
        .toLowerCase();

      const isAllowedType =
        allowedTypes.includes(file.type) ||
        allowedExtensions.includes(fileExt);

      if (!isAllowedType) {
        Modal.error({
          title: "Invalid File Type",
          content: "Only PDF and DOCX files are allowed.",
        });
        return Upload.LIST_IGNORE; // reject
      }

      if (fileList.length > 0) {
        Modal.warning({
          title: "File already exists",
          content: "You must delete the existing file before uploading a new one.",
        });
        return Upload.LIST_IGNORE; // block upload
      }

      setProtocolId(null);
      setIsFileDigitized(false);
      setFileList([file]); // add new file
      return false; // prevent auto upload
    },
    fileList,
    onRemove: (file) => {
      // use same delete handler with confirmation
      handleDelete(file);
      return false; // prevent default removal
    },
    accept: ".pdf,.docx",
  };

  // delete with confirmation
  const handleDelete = (file) => {
    Modal.confirm({
      title: "Delete File",
      content: `Are you sure you want to delete "${file.name}"?`,
      okText: "Yes",
      cancelText: "No",
      onOk: () => {
        setFileList((prev) => prev.filter((item) => item.uid !== file.uid));
        setIsFileDigitized(false);
        setProtocolId(null);
      },
    });
  };

  const handleCollapseChange = (keys) => {
    setActiveKeys(keys.length > 0 ? [keys[keys.length - 1]] : []);
  };

  return (
    <div className="soa">
      <GlobalStyle />
      <Spin spinning={false} tip="Loading, please wait...">
        <div style={{ padding: "14px 10px" }}>
          <Collapse
            defaultActiveKey={['1']}
            style={{
              marginTop: 14,
              background:
                "linear-gradient(20deg, rgba(247, 250, 255, 1) 25%, rgba(240, 245, 255, 1) 50%, rgba(227, 236, 255, 1) 100%)",
              borderColor: "unset",
              border: "unset",
            }}
          >
            <Panel header="Upload Source Document" key="1" collapsible="disabled">
              <Spin spinning={false} tip="Uploading...">
                {/* <Dragger className="custom-dragger" style={{ marginTop: 14 }} {...props}> */}
                <Dragger className="custom-dragger" showUploadList={false} {...props}>
                  <p className="ant-upload-drag-icon">
                    {" "}
                    <InboxOutlined style={{ color: "#27a6a4ff" }} />{" "}
                  </p>
                  <p className="ant-upload-text">Click or Drag file here to upload</p>
                  <p className="ant-upload-hint">Supports PDF/DOCX files</p>
                </Dragger>
                {fileList && fileList?.length !== 0 && (
                  <div>
                    <h6 style={{ fontSize: 11, margin: "5px 0px 0px 5px" }}> Selected File : </h6>
                    {fileList.map((file) => (
                      <span
                        key={file.uid}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          margin: "0px 10px 10px 10px",
                        }}
                      >
                        <span style={{ flex: 1 }}>{file.name}</span>
                        <DeleteOutlined
                          style={{
                            color: "red",
                            cursor: "pointer",
                          }}
                          onClick={() => handleDelete(file)}
                        />
                      </span>
                    ))}
                  </div>
                )}

                <div style={{ marginTop: "1rem" }}></div>
                <IndicationTable onValuesChange={(values) => { setIndication(values) }} />

                {/* <Flex justify="end" style={{ margin: "5px 0px 14px 0px" }}> */}
                <Flex justify="end" style={{ margin: "5px 0px 5px 0px" }}>
                  {!isFileDigitized && (
                    <StyledButton type="primary" onClick={handleUpload} style={{ marginLeft: 10 }}>
                      Upload
                    </StyledButton>
                  )}
                </Flex>
              </Spin>
            </Panel>
          </Collapse>
        </div>
      </Spin>
    </div>
  );
};

export default UploadDoc;
