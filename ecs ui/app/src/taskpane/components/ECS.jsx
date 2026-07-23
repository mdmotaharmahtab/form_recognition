import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Tooltip, Modal, message, Space } from "antd";
import { EyeOutlined } from "@ant-design/icons";
import UploadSourceDocument from "./Ecs/UploadSourceDocument";
import { ECSContext } from "../contexts/ECSContext";
import {
  digitizeProtocol,
  generateLLMECS,
  generateReviewTable,
  getAllEcs,
  getDigitizationPercent,
  getSpecificEcs,
  uploadProtocol,
} from "../../services";
import { useAuth } from "../contexts/AuthContext";
import customMessage from "./customMessage";

const ECS = ({ onBack }) => {
  const [fileList, setFileList] = useState([]);
  const [protocolId, setProtocolId] = useState(null);
  const [dataSource, setDataSource] = useState([]);
  const [tip, setTip] = useState("Loading, please wait...");
  const [loading, setLoading] = useState(false);
  const [isFileDigitized, setIsFileDigitized] = useState(true);
  const [progress, setProgress] = useState(null);
  const [templateProgress, setTemplateProgress] = useState(null);
  const [templateProgressCompleted, setTemplateProgressCompleted] = useState(null);
  const [totalTemplate, setTotalTemplate] = useState(0);
  const [templateLoading, setTemplateLoading] = useState(false);
  const [indication, setIndication] = useState({ indication: "", molecule: "", ta: "" });
  const [versions, setVersions] = useState([])

  const { user } = useAuth();
  console.log(user)

  const pollIntervalRef = useRef(null);
  const abortControllerRef = useRef(null);

  const abortControllerHandle = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort(); // cancels the request
    }
  };

  const clearIntervalHandle = () => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
    }
  };

  const pollDigitizationProgress = (file_id, onComplete) => {
    // clear old interval first
    clearIntervalHandle();

    pollIntervalRef.current = setInterval(async () => {
      try {
        const res = await getDigitizationPercent({ file_id });
        const percent = parseInt(res.response, 10) || 0;
        setProgress(percent);
        setTip(res.message);

        if (percent >= 90) {
          clearInterval(pollIntervalRef.current);
          pollIntervalRef.current = null;
          onComplete?.();
          setProgress(null);
        }
      } catch (err) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
        customMessage.error("Failed to fetch digitization progress.");
        setProgress(null);
        onComplete?.();
      }
    }, 6000);
  };

  const fetchMissingDataForLLM = async (key, row) => {
    const payload = {
      form_name: key,
      fields: row
    };

    const response = await generateLLMECS(payload);
    return response.response || []
  };

  const insertAllRowsIntoExcel = async (rows) => {
    if (!rows || !Array.isArray(rows) || rows.length === 0) return;

    await Excel.run(async (context) => {
      const sheet = context.workbook.worksheets.getActiveWorksheet();
      const table = sheet.tables.getItemOrNullObject("FormData");

      await context.sync();

      const formattedRows = rows.map(item => [
        item.validation_id || "",
        item.indication || "",
        item.molecule || "",
        item.ta || "",
        item.form_name || "",
        item.field_oids || "",
        item.form_field_value || "",
        item.source || "",
        item.validation_logic || "",
        item.reasoning || "",
        item.action || "",
        item.action_details || "",
        item.ecs_id || ""      // HIDDEN UNIQUE KEY
      ]);

      if (table.isNullObject) {
        const newTable = sheet.tables.add("A1:M1", true);
        newTable.name = "FormData";
        newTable.getHeaderRowRange().values = [[
          "VALIDATION ID",
          "INDICATION",
          "MOLECULE",
          "THERAPEUTIC AREA",
          "DOMAIN NAME",
          "FIELD OIDS",
          "VARIABLE TEXT",
          "SOURCE",
          "VALIDATION LOGIC",
          "REASONING",
          "ACTION",
          "ACTION DETAILS",
          "ECS ID"
        ]];

        newTable.style = "TableStyleLight1";
        newTable.rows.add(null, formattedRows);

        // Hide ECS ID column
        newTable.columns.getItemAt(12).getRange().format.columnWidth = 0;
      } else {
        table.rows.add(null, formattedRows);

        // Ensure hidden each time
        table.columns.getItemAt(12).getRange().format.columnWidth = 0;
      }


      await context.sync();
    });
  };

  const processLLMBatches = async (llmRows, batchSize = 5) => {
    // setLoading(true);
    setTemplateLoading(true)
    const unmatchedByForm = {};

    for (const entry of llmRows) {
      const formName = entry.form_name;

      if (!unmatchedByForm[formName]) {
        unmatchedByForm[formName] = [];
      }

      unmatchedByForm[formName].push(entry);
    }
    clearInterval(pollIntervalRef.current);
    let completed = 0;
    const total = llmRows.length;
    setTotalTemplate(total)
    setTip(`Fetching LLM generated rows and inserting into Excel... (0 / ${total})`);

    try {
      for (let i = 0; i < Object.keys(unmatchedByForm).length; i += batchSize) {
        // const batch = llmRows.slice(i, i + batchSize);
        const batch = Object.fromEntries(
          Object.entries(unmatchedByForm).slice(i, i + batchSize)
        );

        const results = await Promise.all(
          Object.entries(batch).map(async ([key, row]) => {

            try {
              const records = await fetchMissingDataForLLM(key, row);
              await insertAllRowsIntoExcel(records);
              // Update progress after each successful row
              completed += records.length;
              setTemplateProgressCompleted(completed)
              setTip(`Fetched and inserted ${completed} / ${total} rows...`);
              return records;
            } catch (err) {
              console.error(`LLM fetch failed for ${row.original_field}`, err);
              completed++;
              setTip(`Fetched and inserted ${completed} / ${total} rows...`);
              return null;
            }
          })
        );

        // Optional: slight pause to keep UI responsive
        await new Promise((res) => setTimeout(res, 100));
      }

      setTip(`✅ All ${total} LLM rows fetched and inserted into Excel!`);
    } finally {
      setTimeout(() => {
        setLoading(false);
        setTemplateLoading(false)
        setTip("");
      }, 1000);
    }
  };


  const uploadAndDigitize = async (base64File, file) => {
    let crf_file_id, file_path;
    // Step 1: Upload
    try {
      const uploadPayload = {
        user_id: user?.homeAccountId,
        file_b64: base64File,
        file_name: file.name,
      };
      const uploadRes = await uploadProtocol(uploadPayload);
      crf_file_id = uploadRes.crf_file_id;
      file_path = uploadRes.file_path;
      // Start polling digitization progress in parallel
      pollDigitizationProgress(crf_file_id, () => {
        console.log("Digitization progress polling completed");
      });

    } catch (err) {
      err.step = "upload";
      throw err;
    }

    // Step 2: Digitize
    try {
      const digitizePayload = {
        created_by: user?.homeAccountId,
        file_id: crf_file_id,
        file_path,
      };
      await digitizeProtocol(digitizePayload, abortControllerRef.current.signal);
    } catch (err) {
      clearIntervalHandle()
      err.step = "digitize";
      throw err;
    }

    // Step 3: Generate Review Table
    try {
      const reviewPayload = {
        file_id: crf_file_id,
        file_path: "",
        ...indication
      };
      const reviewResponse = await generateReviewTable(reviewPayload);
      return reviewResponse
    } catch (err) {
      err.step = "review";
      throw err;
    }
  };

  const handleBase64Upload = async (base64File) => {
    const file = fileList[0];
    setLoading(true);
    setTip("Uploading file...");

    try {
      abortControllerRef.current = new AbortController();
      const result = await uploadAndDigitize(base64File, file);
      // Show table immediately
      setDataSource(result);
      setLoading(false);
      setTip(null);
      message.success("Review table generated!");
      // Insert all initial rows (including LLM placeholder rows) directly into Excel
      const records = result.filter(row => row.source !== "LLM Generated");
      await insertAllRowsIntoExcel(records);
      // LLM background enrichment
      const llmRows = result.filter(row => row.source === "LLM Generated");
      if (llmRows.length > 0) {
        processLLMBatches(llmRows, 10);
      }

    } catch (err) {
      console.error(`Error during ${err.step}:`, err);

      switch (err.step) {
        case "upload":
          customMessage.error("File upload failed. Please try again.");
          break;
        case "digitize":
          customMessage.error("Digitization failed. Please check the file.");
          break;
        case "review":
          customMessage.error("Failed to generate review table.");
          break;
        default:
          customMessage.error("Unexpected error occurred.");
      }

      setLoading(false);
      setProgress(null);
      setProtocolId(null);
      setIsFileDigitized(false);
    }
  };

  const highlightExcelRow = async (record) => {
    await Excel.run(async (context) => {
      const sheet = context.workbook.worksheets.getActiveWorksheet();
      const table = sheet.tables.getItemOrNullObject("FormData");
      await context.sync();

      if (table.isNullObject) {
        console.warn("FormData table not found.");
        return;
      }

      const dataRange = table.getDataBodyRange();
      dataRange.load("values");
      await context.sync();

      const values = dataRange.values;
      const matchIndex = values.findIndex((r) => r[12] === record.ecs_id);

      if (matchIndex === -1) {
        console.warn("Row not found in Excel table.");
        return;
      }

      const targetRow = dataRange.getRow(matchIndex);
      // Clear previous highlights first
      dataRange.format.fill.clear();
      // Apply highlight
      targetRow.format.fill.color = "#FFE58F"; // light yellow
      targetRow.select(); // optional scroll
      await context.sync();
      // Auto-clear highlight after 3 seconds
      setTimeout(async () => {
        await Excel.run(async (ctx) => {
          const sheet = ctx.workbook.worksheets.getActiveWorksheet();
          const table = sheet.tables.getItemOrNullObject("FormData");
          const range = table.getDataBodyRange();
          range.load("values");
          await ctx.sync();

          if (matchIndex >= 0 && matchIndex < range.getRowCount()) {
            const targetRow = range.getRow(matchIndex);
            targetRow.format.fill.clear();
            await ctx.sync();
          }
        });
      }, 3000);
    });
  };

  const onSelectVersion = async (version) => {
    const crf_file_id = version?.crf_file_id
    setLoading(true)
    const res = await getSpecificEcs({ crf_file_id: crf_file_id })
    const records = res.filter(row => row.source !== "LLM Generated");
    setDataSource(records);
    try {
      await insertAllRowsIntoExcel(records);
      const llmRows = res.filter(row => row.source === "LLM Generated");
      console.log(`llmRows: `, llmRows)
      if (llmRows.length > 0) {
        processLLMBatches(llmRows, 10);
      }
    } catch (error) {
      console.log("Error: ", error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setLoading(true)
    getAllEcs({ user_id: user?.homeAccountId })
      .then(res => setVersions(res.versions))
      .catch(err => console.log(`Error fetching all ecs: ${err}`))
      .finally(() => setLoading(false))
  }, [])

  const columns = [
    {
      title: "Form",
      dataIndex: "form_name",
      key: "form_name",
      width: 150,
      ellipsis: true,
    },
    {
      title: "Field",
      dataIndex: "field_oids",
      key: "field_oids",
      width: 100,
      ellipsis: true,
    },
    {
      title: "Action",
      key: "action",
      width: 50,
      render: (_, record, index) => (
        <div>
          <Space size="small">
            <Tooltip title="highlight Excel Row">
              <EyeOutlined
                style={{ color: "#426bba !important", cursor: "pointer" }}
                onClick={() => highlightExcelRow(record)}
              />
            </Tooltip>
          </Space>
        </div>
      ),
    },
  ];

  const handleBack = () => {
    const isFileListEmpty = fileList.length === 0;

    const modalTitle = isFileListEmpty ? "Are you sure ?" : "Discard Changes?";

    const modalContent = isFileListEmpty
      ? "Do you want to go back?"
      : "Your file will be discarded if you go back. Are you sure?";

    Modal.confirm({
      title: modalTitle,
      content: modalContent,
      okText: "Yes, Go Back",
      cancelText: "Stay",
      okType: "danger",
      onOk() {
        if (!isFileDigitized) {
          abortControllerHandle();
          clearIntervalHandle();
          onBack();
        }
        setProtocolId(null);
        setIsFileDigitized(false);
        setFileList([]);
        setDataSource([]);
      },
      onCancel() {
        console.log("Stay on page");
      },
    });
  };

  const ecsContextValue = {
    loading,
    setLoading,
    setFileList,
    fileList,
    handleBase64Upload,
    dataSource,
    columns,
    loading,
    onClickGenerate: () => { },
    handleBack,
    onBack,
    tip,
    setTip,
    isFileDigitized,
    setIsFileDigitized,
    progress,
    protocolId,
    setProtocolId,
    templateProgress,
    templateProgressCompleted,
    totalTemplate,
    templateLoading,
    indication,
    setIndication,
    versions,
    onSelectVersion
  };

  return (
    <ECSContext.Provider value={ecsContextValue}>
      <UploadSourceDocument />
    </ECSContext.Provider>
  );
};

export default ECS;

Office.onReady().then(() => {
  const root = document.getElementById("ECS_container");
  if (root) {
    console.log("Inside if");
    createRoot(root).render(<ECS />);
  } else {
    console.log("Root element not found");
  }
});
