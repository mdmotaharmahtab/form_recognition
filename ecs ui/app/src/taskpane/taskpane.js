import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";
import remarkRehype from "remark-rehype";
import rehypeRaw from "rehype-raw";
import rehypeStringify from "rehype-stringify";

// global Word console
export async function insertText(text) {
  try {
    await Word.run(async (context) => {
      let body = context.document.body;

      // Split the glossary text by new lines (\n)
      const lines = text.split("\n");

      let formattedText = `<div style="font-weight: bold; font-size: 30px; text-align:center;">Glossary</div><br><br><br>`;
      lines.forEach((line) => {
        let [boldText, descText] = line.split(":");

        if (boldText && descText) {
          // Format the text with bold for the first part and regular for the second
          formattedText += `<span style="font-weight: bold; font-size: 15px">${boldText}:</span> ${descText}<br>`;
        }
      });

      // Insert the formatted text with line breaks
      body.insertHtml(formattedText, Word.InsertLocation.end);
      await context.sync();
    });
  } catch (error) {
    console.log("Error inserting glossary text: " + error);
  }
}

export async function getDocumentName() {
  return new Promise((resolve, reject) => {
    Office.onReady((info) => {
      if (info.host === Office.HostType.Word) {
        const documentUrl = Office.context.document.url;

        if (documentUrl) {
          const matchResult = documentUrl.match(/[\\\/]([^\\\/]+)(?=\.docx$)/);

          if (matchResult) {
            resolve(matchResult[1]);
          } else {
            console.warn("The URL does not match the expected format.");
            resolve(null);
          }
        } else {
          console.warn("Document URL is not available.");
          resolve(null);
        }
      } else {
        reject("Not running in Word host");
      }
    });
  });
}

export async function getHtmlBetweenSections(sectionsArray, currentIndex) {
  return Word.run(async (context) => {
    let section1 = sectionsArray[currentIndex]?.section_name || "";
    section1 = section1.replace(/[\n\r\t\f\v\u2028\u2029]+/g, "").trim();

    const body = context.document.body;

    const result1 = body.search(section1, {
      matchCase: false,
      matchWholeWord: false,
      ignorePunct: true,
      ignoreSpace: true,
    });
    result1.load("items");

    await context.sync();

    if (result1.items.length === 0) {
      console.warn(`Section 1 "${section1}" not found`);
      return "";
    }

    const section1End = result1.items[0].getRange("End");
    let endRange = body.getRange("End"); // Default fallback
    let foundNextSection = false;

    for (let j = currentIndex + 1; j < sectionsArray.length; j++) {
      let sectionNext = sectionsArray[j]?.section_name || "";
      sectionNext = sectionNext.replace(/[\n\r\t\f\v\u2028\u2029]+/g, "").trim();
      if (!sectionNext) continue;

      const resultNext = body.search(sectionNext, {
        matchCase: false,
        matchWholeWord: false,
        ignorePunct: true,
        ignoreSpace: true,
      });
      resultNext.load("items");

      await context.sync();

      if (resultNext.items.length === 0) {
        continue; // section not found — try next
      }

      const startOfNext = resultNext.items[0].getRange("Start");
      startOfNext.load("start"); // Ensure startOfNext is loaded
      await context.sync(); // Sync after loading startOfNext

      endRange = startOfNext;
      break;
    }

    const range = section1End.expandTo(endRange);
    range.load(["html", "text"]);
    await context.sync();

    if (!range.text || range.text.trim() === "") {
      console.warn("⚠️ No content found between sections.");
      return "";
    }

    return range.getHtml() || "";
  }).catch((error) => {
    console.error("Error in getHtmlBetweenSections:", error);
    return "";
  });
}

// Replace HTML content between two section headings
export async function replaceHtmlBetweenSections(sectionsArray, currentIndex, htmlToInsert) {
  const section1 = sectionsArray[currentIndex]?.section_name?.replace(/[\n\r\t\f\v\u2028\u2029]+/g, "").trim() || "";

  return Word.run(async (context) => {
    const body = context.document.body;

    const result1 = body.search(section1, {
      matchCase: false,
      matchWholeWord: false,
      ignorePunct: true,
      ignoreSpace: true,
    });
    result1.load("items");

    await context.sync();

    if (result1.items.length === 0) {
      console.warn(`Section 1 "${section1}" not found`);
      return;
    }

    const startRange = result1.items[0].getRange("End");
    let endRange = body.getRange("End");

    // Search for the next found section starting from currentIndex + 1
    for (let j = currentIndex + 1; j < sectionsArray.length; j++) {
      const sectionNext = sectionsArray[j]?.section_name?.replace(/[\n\r\t\f\v\u2028\u2029]+/g, "").trim();
      if (!sectionNext) continue;

      const nextSearch = body.search(sectionNext, {
        matchCase: false,
        matchWholeWord: false,
        ignorePunct: true,
        ignoreSpace: true,
      });
      nextSearch.load("items");

      await context.sync();

      if (nextSearch.items.length === 0) {
        continue; // section not found — try next
      }

      if (nextSearch.items.length > 0) {
        endRange = nextSearch.items[0].getRange("Start");
        break;
      }
    }

    const rangeToReplace = startRange.expandTo(endRange);
    rangeToReplace.clear();
    startRange.insertHtml(`<p>${htmlToInsert}</p><br>`, Word.InsertLocation.start);

    await context.sync();
    console.log("HTML inserted between sections.");
  }).catch((error) => {
    console.error("Error in replaceHtmlBetweenSections:", error);
  });
}

export async function insertTemplateIntoWord(sections) {
  return Word.run(async (context) => {
    try {
      if (!sections || sections.length === 0) {
        console.log("No content to insert. The API response was empty.");
        return;
      }

      sections.forEach((section) => {
        const range = context.document.getSelection();
        // Insert Section Title
        const titleRange = range.insertText("\n\n" + section.section_name + "\n\n", Word.InsertLocation.end);
        titleRange.font.name = "Arial";
        titleRange.font.size = 14;
        titleRange.font.color = "black";
        titleRange.font.bold = true;

        // Insert Generated Text
        if (section.generatedText) {
          const isHtml = /<\/?[a-z][\s\S]*>/i.test(section.generatedText.trim());

          if (isHtml) {
            const inserted = range.insertHtml(`${section.generatedText}<br><br>`, Word.InsertLocation.end);
            inserted.font.name = "Times New Roman";
            inserted.font.size = 12;

            const newLine = range.insertHtml("<br>", Word.InsertLocation.end);
            newLine.select(Word.SelectionMode.start);
          } else {
            const textRange = range.insertText(section.generatedText + "\n\n", Word.InsertLocation.end);
            textRange.font.name = "Times New Roman";
            textRange.font.size = 12;
            textRange.font.bold = false;

            const newLine = range.insertHtml("<br>", Word.InsertLocation.end);
            newLine.select(Word.SelectionMode.start);
          }
        }
        // range.select(Word.SelectionMode.end);
      });
      await context.sync();
    } catch (error) {
      console.error("Failed to insert fetched content into the document. Please try again:", error);
    }
  });
}

function resizeImages() {
  return (tree) => {
    // Loop through the tree nodes
    for (const node of tree.children || []) {
      // Check if the current node is an image element
      if (node.type === "element" && node.tagName === "img") {
        const src = node.properties?.src;

        // Only resize base64 images (optional check for type)
        if (typeof src === "string" && src.startsWith("data:image")) {
          // Set width and height directly as attributes (636px width, 408px height)
          node.properties.width = 620;
          node.properties.height = 408;
        }
      }

      // Loop through the children of the current node, if any
      for (const child of node.children || []) {
        // Check if the child is an image and apply resizing
        if (child.type === "element" && child.tagName === "img") {
          const src = child.properties?.src;

          if (typeof src === "string" && src.startsWith("data:image")) {
            // Set width and height directly as attributes (636px width, 408px height)
            child.properties.width = 620;
            child.properties.height = 408;
          }
        }
      }
    }
  };
}

export async function insertTextIntoWord(summary) {
  summary = {
    content_type_list: [],
    ...summary,
  };
  console.log(summary);

  return Word.run(async (context) => {
    try {
      const selection = context.document.getSelection();
      const findDocumentIndex = summary?.content_type_list?.filter((e, i) => e === "Document")?.map((_, i) => i) || [];

      const inputDataString =
        summary?.input_data
          ?.map((item, i) => {
            if (findDocumentIndex?.includes(i) || !summary?.content_type_list?.length) {
              return "";
            } else {
              return `<div>${item}</div><br>`;
            }
          })
          ?.join("<br>") || "";

      const imgData =
        summary?.images
          ?.map((e) => {
            const imgdesc = e?.imgdesc || "";
            const imgpath = e?.imgpath || "";
            return `<div>
                    <h5 style="font-size: 12px;">${imgdesc}</h5>
                    </div>
                    <div style="background-color: #f5f5f5; padding: 12px; border-radius: 8px; margin-bottom: 16px;">
                    <img
                      src="data:image/jpeg;base64,${imgpath}"
                      alt="Rendered Image"
                      style="width: 100%; max-width: 600px;"
                    />
                    </div>
                    `;
          })
          ?.join("<br>") || "";

      // const imgData =
      // summary?.Images
      //   ?.map((item, i) => {
      //     if () {
      //       return "";
      //     } else {
      //       return `<div>${item}</div><br>`;
      //     }
      //   })
      //   ?.join("<br>") || "";

      // Convert Markdown to HTML manually
      let processedMarkdown = "";
      if (summary?.generatedText?.includes("<!DOCTYPE html>")) {
        processedMarkdown = summary?.generatedText;
      } else {
        let markdownContent = summary?.generatedText?.replace(/<\/table>/g, "</table>\n\n") || "";
        processedMarkdown = await unified()
          .use(remarkParse) // Parse Markdown
          .use(remarkGfm) // Support GitHub-Flavored Markdown (tables, checkboxes, etc.)
          .use(remarkRehype, { allowDangerousHtml: true }) // Convert Markdown to HTML tree, preserving HTML
          .use(rehypeRaw) // Allow raw HTML inside Markdown
          .use(rehypeStringify)
          .use(resizeImages) // Convert the HTML tree to a string
          .process(markdownContent);
      }

      const soaPrefixHtml = summary?.isSoa
        ? `<div style="font-size: 16px; font-weight: bold; font-family: 'Calibri', sans-serif;">
            ${summary?.table_name || ""} 
          </div>`
        : "";
      const footnotesdata = summary?.footnotes ? `<br>${summary?.footnotes}<br>` : "";

      selection.insertHtml(
        `${inputDataString}
        ${soaPrefixHtml}
        <div class="generatedText" style="font-size: 16px; color: #000000; font-family: 'Calibri', sans-serif;">
          ${processedMarkdown}
        </div>
         ${footnotesdata}
        <br>
        ${imgData}
        `,
        // ${summary?.generatedText?.replace(/\n/g, "<br>")}
        // <img src="data:image/jpeg;base64,${byteData}" style="width: 100%; max-width: 600px;" />`,
        Word.InsertLocation.replace
      );
      selection.select(Word.SelectionMode.end);
      await context.sync();
    } catch (error) {
      console.error("Error generating summary:", error);
      if (error instanceof OfficeExtension.Error) {
        console.error("Debug info:", JSON.stringify(error.debugInfo));
      }
    }
  });
}

// Function to read the selected content of the Word document using Office.js
// export async function initializeOffice() {
//   Office.onReady(function (info) {
//     if (info.host === Office.HostType.Word) {
//       document.getElementById("getSelectedText").onclick = async function () {
//         try {
//           await Word.run(async function (context) {
//             var selection = context.document.getSelection();
//             context.load(selection);
//             await context.sync();
//             console.log("Selected Text: " + selection.text);
//           });
//         } catch (error) {
//           console.log("Error: " + error);
//         }
//       };
//     }
//   });
// }

// Function to read the content of the Word document using Office.js

export async function readWordContent() {
  return Word.run(async (context) => {
    // Get the entire body content of the document
    const body = context.document.body;
    // Load the text from the body of the document
    body.load("text");
    // Synchronize the context to populate the body text
    await context.sync();
    // console.log("Word Content:", body.text);
    return body.text;
  }).catch(function (error) {
    console.log("Error reading Word document content: " + error.message);
  });
}

export async function insertGeneratedTextWithSectionIntoWord(insertText) {
  return Word.run(async (context) => {
    try {
      const range = context.document.getSelection();
      range.insertHtml(insertText, Word.InsertLocation.end);
      range.select(Word.SelectionMode.end);

      await context.sync();
    } catch (error) {
      console.error("Failed to insert fetched content into the document. Please try again:", error);
    }
  });
}

export const handleFindAndReplace = async (findText, replaceText) => {
  await Word.run(async (context) => {
    // Search for the text in the Word document's body
    const searchResults = context.document.body.search(findText, {
      matchCase: false,
      matchWholeWord: true,
    });

    // Load the search results so we can access them
    context.load(searchResults);
    await context.sync();

    // If results are found, replace them with the replace text
    if (searchResults.items.length > 0) {
      searchResults.items.forEach((item) => {
        // Insert the replacement text
        item.insertHtml(replaceText, Word.InsertLocation.replace);
      });
      await context.sync();
    } else {
    }
  });
};

export const handleFindSearchCheck = (findText) => {
  return new Promise((resolve, reject) => {
    Word.run(async (context) => {
      // Search for the text in the Word document's body
      const searchResults = context.document.body.search(findText, {
        matchCase: false,
        matchWholeWord: true,
      });

      context.load(searchResults);
      await context.sync();

      if (searchResults.items.length > 0) {
        resolve(true); // Found the text, resolve as true
      } else {
        resolve(false); // Not found, resolve as false
      }
    }).catch((error) => {
      reject(error); // Reject the promise if an error occurs
    });
  });
};

export const replaceTextInWord = async (generatedText, summarizedText) => {
  try {
    await Word.run(async (context) => {
      const body = context.document.body;

      // Load the text property of the document body
      body.load("text");
      await context.sync();

      const bodyText = body.text;

      // Check if the generatedText exists in the document
      if (!bodyText.includes(generatedText)) {
        console.log("Generated text not found in the document.");
        return;
      }

      // Replace the generated text with the summarized text
      const updatedText = bodyText.replaceAll(generatedText, summarizedText);

      // Clear the document body and insert the updated text
      body.clear(); // Clear the existing content
      body.insertText(updatedText, Word.InsertLocation.start); // Insert the updated content

      await context.sync();
      console.log("Text replaced successfully in the document.");
    });
  } catch (error) {
    console.error("Error replacing text in the Word document:", error);
  }
};

export const getSectionContext = async () => {
  try {
    return await Word.run(async (context) => {
      const body = context.document.body;
      // Get the HTML content directly
      const htmlContent = body.getHtml();
      await context.sync();
      console.log(htmlContent.value);
    });
  } catch (error) {
    console.error("Error reading document content as HTML:", error);
    throw error;
  }
};



export const getConfidenceStyle = (score) => {
  const value = parseFloat(score ?? 0);   // handles string or number
  const percentage = Math.round(value * 100);

  console.log("value: ", value)
  console.log("percentage: ", percentage)

  let background = "#fdecea";
  let color = "#c62828";

  if (value >= 0.85) {
    background = "#e6f7e6";
    color = "#2e7d32";
  } else if (value >= 0.65) {
    background = "#fff4e5";
    color = "#e65100";
  }

  return {
    percentage,
    style: {
      // background,
      color,
      minWidth: 55,
      textAlign: "center",
      padding: "2px 8px",
      borderRadius: 4,
      fontSize: 11,
      fontWeight: 600
    }
  };
};

const formatReasonForExcel = (text) => {
  if (!text) return "";

  return text
    .replace(/\u00A0/g, " ")
    .replace(/^\s+/gm, "")
    .replace(/•/g, "")                       // remove bullets
    .replace(/\*\*(.*?)\*\*/g, "$1")         // remove bold markdown
    .replace(/:\s*/g, ":\n")                 // break after headings
    .replace(/\n{2,}/g, "\n\n")              // spacing
    .trim();
};

export const writeCCMResponseToExcel = async (responseData) => {

  try {

    const records = responseData.filter(r => r.file_id);
    if (!records?.length) return;

    await Excel.run(async (context) => {

      const sheetName = "PV Review";
      let sheet = context.workbook.worksheets.getItemOrNullObject(sheetName);
      await context.sync();

      if (sheet.isNullObject) {
        sheet = context.workbook.worksheets.add(sheetName);
      }

      /* ---------------------------
         Header Mapping
      ----------------------------*/

      const questionMap = {
        safety_reporting_language:
          "Does the contract contain safety reporting language?",
        safety_reporting_methodology:
          "Does the contract contain the methodology for how safety information should be reported to Otsuka?",
        pv_subcontracting_restriction:
          "Does the contract contain subcontracting language that notes PV activities should not be subcontracted without written approval from Otsuka?",
        audit_inspection_rights:
          "Does the contract contain audit and inspection language that the third party can be audited by Otsuka or inspected by relevant authority?"
      };

      const baseHeaderMap = {
        file_name: "File Name",
        is_pv: "Safety Assessment (PV or Non-PV)",
        pv_confidence: "Safety Assessment Confidence",
        reason: "Safety Assessment Reason",
        classification_comment: "Classification Comment",
        extraction_comment: "Extraction Comment",
        created_at: "Current Timestamp",
        orig_language: "Language",
        feedback: "Safety Assessment Liked"
      };

      const formatHeader = (key) => {
        const cleanKey = key
          .replace(/_value$/, "")
          .replace(/_confidence$/, "")
          .replace(/_liked$/, "");

        if (cleanKey === "Territory of Activity") {
          if (key.endsWith("_liked")) return "Territory Liked";
          if (key.endsWith("_confidence")) return "Territory Confidence";
          return "Territory";
        }

        if (baseHeaderMap[cleanKey]) return baseHeaderMap[cleanKey];

        if (questionMap[cleanKey]) {
          if (key.endsWith("_confidence")) return `${questionMap[cleanKey]} Confidence`;
          if (key.endsWith("_liked")) return `${questionMap[cleanKey]} Liked`;
          return questionMap[cleanKey];
        }

        const label = cleanKey.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());

        if (key.endsWith("_confidence") && cleanKey !== "pv_confidence") {
          return `${label} Confidence`;
        }
        if (key.endsWith("_liked")) return `${label} Liked`;

        return label;
      };

      /* ---------------------------
         Metadata Keys
      ----------------------------*/

      const metadataKeys = new Set();
      records.forEach(r => {
        if (r.metadata) Object.keys(r.metadata).forEach(k => metadataKeys.add(k));
      });

      const metadataColumns = Array.from(metadataKeys);

      /* ---------------------------
         PV REVIEW
      ----------------------------*/

      const baseHeaders = ["file_name", "is_pv", "reason", "orig_language"];

      const headers = [
        ...baseHeaders,
        ...metadataColumns.map(k => `${k}_value`)
      ].map(formatHeader);

      const rows = records.map(record => {

        const baseValues = [
          record.file_name,
          record.is_pv === true ? "PV" : record.is_pv === false ? "Non-PV" : "",
          formatReasonForExcel(record.reason),
          record.orig_language || ""
        ];

        const metadataValues = metadataColumns.map(k => {
          if (k === "Territory of Activity") {
            return record.metadata?.[k]?.metadata_key || "";
          }
          return record.metadata?.[k]?.metadata_key || "";
        });

        return [...baseValues, ...metadataValues];
      });

      const values = [headers, ...rows];

      sheet.getUsedRange()?.clear();

      const range = sheet.getRangeByIndexes(0, 0, values.length, headers.length);
      range.values = values;

      sheet.getRangeByIndexes(0, 0, 1, headers.length).format.font.bold = true;
      sheet.getUsedRange().format.autofitColumns();
      // Pin PV Review as the first tab
      sheet.position = 0;

      /* ---------------------------
         PV FEEDBACK (FIXED)
      ----------------------------*/

      const feedbackSheetName = "PV Feedback";
      let feedbackSheet = context.workbook.worksheets.getItemOrNullObject(feedbackSheetName);
      await context.sync();

      if (feedbackSheet.isNullObject) {
        feedbackSheet = context.workbook.worksheets.add(feedbackSheetName);
      }

      // PV Feedback as second tab
      feedbackSheet.position = 1;

      const feedbackHeaders = [
        baseHeaderMap["feedback"],
        baseHeaderMap["pv_confidence"],
        baseHeaderMap["created_at"],
        baseHeaderMap["classification_comment"],
        baseHeaderMap["extraction_comment"],
        ...metadataColumns.map(k => formatHeader(`${k}_confidence`)),
        ...metadataColumns.map(k => formatHeader(`${k}_liked`))
      ];

      const feedbackRows = records.map(record => {

        const baseValues = [
          record.feedback === true ? "Yes" : record.feedback === false ? "No" : "",
          record.pv_confidence ?? "",
          formatTimestamp(record.created_at),
          record.classification_comment ?? "",
          record.extraction_comment ?? ""
        ];

        const metadataConfidence = metadataColumns.map(k =>
          record.metadata?.[k]?.confidence_score ?? ""
        );

        const metadataLiked = metadataColumns.map(k => {
          const val = record.metadata?.[k]?.feedback ?? record.metadata?.[k]?.is_liked;

          if (val === true) return "Yes";
          if (val === false) return "No";
          return "";
        });

        return [...baseValues, ...metadataConfidence, ...metadataLiked];
      });

      const columnCount = feedbackHeaders.length;

      const normalizedValues = [feedbackHeaders, ...feedbackRows].map(row => {
        const r = [...row];
        while (r.length < columnCount) r.push("");
        if (r.length > columnCount) r.length = columnCount;
        return r;
      });

      feedbackSheet.getUsedRange()?.clear();

      const feedbackRange = feedbackSheet.getRangeByIndexes(
        0,
        0,
        normalizedValues.length,
        columnCount
      );

      feedbackRange.values = normalizedValues;

      feedbackSheet.getRangeByIndexes(0, 0, 1, columnCount).format.font.bold = true;
      feedbackSheet.getUsedRange().format.autofitColumns();

      sheet.activate();

      await context.sync();

    });

  } catch (error) {
    console.error("Excel write failed:", error);
  }

};

const formatTimestamp = (timestamp) => {
  if (!timestamp) return "";

  return new Date(timestamp).toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: true
  });
};