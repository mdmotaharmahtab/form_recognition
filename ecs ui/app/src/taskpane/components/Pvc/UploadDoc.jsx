import React, { useRef, useState } from "react";
import { Button, Flex, Upload, Spin, message, Collapse, Modal } from "antd";
import { InboxOutlined } from "@ant-design/icons";
import styled, { createGlobalStyle } from "styled-components";
import { usePvc } from "../Pvc/usePvc";
import { fileToBase64 } from "../../../services";
import FileTable from "./FileTable";
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
  /* NEW: make the panel header look like a plain label */
  .no-toggle-panel > .ant-collapse-header {
    cursor: default !important;
    pointer-events: none;
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

// Remove the Collapse and Panel imports usage, replace with this:

const SectionCard = styled.div`
  margin-top: 14px;
  background: linear-gradient(
    20deg,
    rgba(247, 250, 255, 1) 25%,
    rgba(240, 245, 255, 1) 50%,
    rgba(227, 236, 255, 1) 100%
  );
  border-radius: 8px;
  padding: 12px 16px;
`;

const SectionTitle = styled.p`
  color: #426bba;
  font-weight: 500;
  font-size: 14px;
  margin: 0 0 12px 0;
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
    tip,
    setTip,
    jobId,
    setJobId,
    onClickGenerate
  } = usePvc();

  // Tracks whether the current drag/drop or file-picker batch needs to clear
  // the existing list before appending. Set to true on the first file of a new
  // batch (when jobId is present), then flipped to false so subsequent files in
  // the same batch append instead of clearing again.
  const pendingResetRef = useRef(false);

  const handleUpload = async () => {
    if (!fileList || fileList.length === 0) {
      message.warning("Please select a file to upload.");
      return;
    }
    setLoading(true);
    setTip("Files are being uploaded...");
    try {
      const base64Files = await Promise.all(
        fileList.map(async (file) => ({
          file_name: file.name,
          file_base64: await fileToBase64(file),
        }))
      );

      handleBase64Upload(base64Files);
    } catch (err) {
      message.error("Failed to process files");
      console.error(err);
    }
  };

  const props = {
    multiple: true,
    beforeUpload: (file) => {
      const allowedTypes = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      ];
      const allowedExtensions = [".pdf", ".docx"];
      const fileExt = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
      const isAllowedType =
        allowedTypes.includes(file.type) || allowedExtensions.includes(fileExt);

      if (!isAllowedType) {
        Modal.error({
          title: "Invalid File Type",
          content: "Only PDF and DOCX files are allowed.",
        });
        return Upload.LIST_IGNORE;
      }

      // First file of a new batch after returning from dialog:
      // arm the reset flag so this batch starts from a clean list.
      if (jobId && !pendingResetRef.current) {
        pendingResetRef.current = true;
        setJobId(null);
      }

      setFileList((prev) => {
        // If a reset is pending, discard the old list and start fresh.
        // Flip the flag immediately so subsequent files in the same batch append.
        if (pendingResetRef.current) {
          pendingResetRef.current = false;
          return [file];
        }
        return [...prev, file];
      });

      return false; // prevent auto upload
    },
    fileList,
    onRemove: (file) => {
      handleDelete(file);
      return false;
    },
    accept: ".pdf,.docx",
  };

  const handleDelete = (file) => {
    Modal.confirm({
      title: "Delete File",
      content: `Are you sure you want to delete "${file.name}"?`,
      okText: "Yes",
      cancelText: "No",
      onOk: () => {
        setFileList((prev) => prev.filter((item) => item.uid !== file.uid));
      },
    });
  };

  return (
    <div className="soa">
      <GlobalStyle />
      <Spin spinning={loading} tip={tip}>
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
            <SectionCard>
              <SectionTitle>Upload Source Document</SectionTitle>
              <Spin spinning={false} tip="Uploading...">
                <Dragger className="custom-dragger" showUploadList={false} {...props}>
                  <p className="ant-upload-drag-icon">
                    <InboxOutlined style={{ color: "#27a6a4ff" }} />
                  </p>
                  <p className="ant-upload-text">Click or Drag file here to upload</p>
                  <p className="ant-upload-hint">Supports PDF/DOCX files</p>
                </Dragger>

                <div style={{ marginTop: "1rem" }}></div>
                {fileList?.length > 0 && (
                  <FileTable
                    fileList={fileList}
                    jobId={jobId}
                    onRemove={(file) =>
                      setFileList((prev) => prev.filter((f) => f.uid !== file.uid))
                    }
                  />
                )}
                <Flex justify="end" style={{ margin: "5px 0px 5px 0px" }}>
                  {jobId && fileList?.length > 0 ? (
                    <StyledButton
                      type="primary"
                      onClick={() => onClickGenerate(jobId)}
                      style={{ marginLeft: 10 }}
                    >
                      Generate Assessment
                    </StyledButton>
                  ) : (
                    <StyledButton
                      type="primary"
                      onClick={handleUpload}
                      style={{ marginLeft: 10 }}
                    >
                      Upload
                    </StyledButton>
                  )}
                </Flex>
              </Spin>
            </SectionCard>
          </Collapse>
        </div>
      </Spin>
    </div>
  );
};

export default UploadDoc;