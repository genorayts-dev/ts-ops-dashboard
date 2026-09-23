/**
 * 독립(standalone) Apps Script — 통합 구글시트에 이미 다른 자동화(웹앱)가 떠 있어서
 * 그 스크립트에 얹지 않고 완전히 별개의 프로젝트로 배포한다. 시트에 바인딩하지 않고
 * SpreadsheetApp.openById() 로 ID 지정해서 열기 때문에, 기존 자동화의 doPost/doGet 과
 * 절대 충돌하지 않는다(Apps Script 프로젝트가 통째로 다르므로).
 *
 * 배포 방법:
 *   1) https://script.google.com → 새 프로젝트
 *   2) 기본 코드를 지우고 이 파일 내용 전체를 붙여넣기
 *   3) SECRET 값을 backend/.env 의 TSD_GENO_ONE_SHEET_SECRET 과 동일하게 맞추기
 *      (이미 맞춰져 있으면 그대로 두면 됨)
 *   4) 저장(Ctrl+S) → 배포 → 새 배포 → 유형 선택(⚙️) → 웹 앱
 *        - 실행 계정: 나
 *        - 액세스 권한: 모든 사용자 (서버가 로그인 없이 호출하므로 "모든 사용자"여야 함.
 *          보안은 Google 로그인이 아니라 아래 SECRET 값으로 함)
 *   5) 배포 클릭 → 처음 한 번은 "권한 검토" 화면이 뜸 → 본인 계정으로 승인
 *      (이 스크립트가 시트에 접근하도록 허용하는 절차 — 정상)
 *   6) 상단 함수 목록에서 testWrite 선택 → ▶ 실행 버튼 클릭 → 다시 한 번 권한 승인
 *      화면이 뜸 → 승인 (읽기 권한과 쓰기 권한은 별도라서 이 단계가 꼭 필요함.
 *      안 하면 웹 앱에서 실제 쓰기 시도 시 에러 대신 구글 로그인 안내 페이지가 돌아옴)
 *   7) 생성된 웹 앱 URL을 저에게 알려주세요
 *   8) 코드 바뀌면 "배포 관리 → 수정 → 새 버전"으로 재배포해야 반영됨(URL은 유지됨)
 */

var SECRET = "b5W1lNbB_GrkmUa-1uLG9pM0Kljw7wBODqWyS3Li1h0";
var SHEET_ID = "1EqKrXRWWuDZv9j11iUHDOQmN0cDwAp47dBWvv1SyV7Q"; // 통합 구글시트 ID

function doPost(e) {
  try {
    var body = JSON.parse(e.postData.contents);
    if (body.secret !== SECRET) {
      return _json({ ok: false, error: "unauthorized" });
    }
    var ss = SpreadsheetApp.openById(body.sheet_id || SHEET_ID);
    var sheet = body.tab_needles
      ? _findTabByNeedles(ss, body.tab_needles)
      : ss.getSheetByName(body.tab);
    if (!sheet) {
      var names = ss.getSheets().map(function (s) { return s.getName(); });
      return _json({
        ok: false,
        error: "tab not found: " + (body.tab || JSON.stringify(body.tab_needles)),
        available_tabs: names,
      });
    }
    var rows = body.rows;
    if (!rows || !rows.length) {
      return _json({ ok: false, error: "rows is empty" });
    }
    sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows);
    return _json({ ok: true, inserted: rows.length, tab: body.tab });
  } catch (err) {
    return _json({ ok: false, error: String(err) });
  }
}

// 외부 자동화 스크립트가 탭 이름을 수시로 바꿔서(공백/대괄호/슬래시 등) 정확한
// 이름 대신 "이 문자열들을 다 포함하는 탭"으로 매번 실시간(캐시 없이) 찾는다.
// 파이썬 쪽 gsheet_master.py 의 _norm_tab() 과 동일한 정규화 규칙.
function _normTab(s) {
  return s.replace(/[ \[\]\/]/g, "");
}

function _findTabByNeedles(ss, needles) {
  var sheets = ss.getSheets();
  for (var i = 0; i < sheets.length; i++) {
    var name = sheets[i].getName();
    if (name.indexOf("_") === 0) continue; // 내부 스테이징 탭 제외
    var norm = _normTab(name);
    var allMatch = needles.every(function (n) {
      return norm.indexOf(_normTab(n)) !== -1;
    });
    if (allMatch) return sheets[i];
  }
  return null;
}

/**
 * 수동 1회 실행용 — 에디터에서 이 함수를 직접 ▶ 실행하면 Google이 "이 앱이
 * 스프레드시트를 수정하도록 허용하시겠습니까" 승인 화면을 띄운다(승인 필요).
 * 웹 앱으로 배포만 하고 실제 쓰기(setValues)는 한 번도 실행 안 해본 상태라
 * 그 상태로 백엔드에서 doPost 로 처음 쓰기를 시도하면 승인 안 된 권한이라
 * 조용히 실패한다(에러 대신 구글 인증 안내 페이지 HTML이 돌아옴). 이 함수를
 * 딱 한 번 에디터에서 직접 실행해서 승인해주면 그 뒤로는 doPost 의 실제
 * setValues 쓰기도 정상 동작한다. 실행 후 시트 맨 끝에 테스트 행이 하나
 * 추가되는데(직접 지워도 무방) 그게 바로 승인이 됐다는 증거.
 */
function testWrite() {
  var ss = SpreadsheetApp.openById(SHEET_ID);
  var sheet = _findTabByNeedles(ss, ["MD", "AS"]);
  if (!sheet) throw new Error("tab not found");
  sheet.appendRow(["__TEST__", "권한 승인 테스트 행 — 지워도 됩니다"]);
}

/**
 * 진단용 — 백엔드에서 9컬럼 이상 쓰면 실패하는 걸 재현한다. 이 함수를 에디터에서
 * 직접 ▶ 실행하면(doPost 를 거치지 않으므로 내 try/catch 가 없음) 에러가 나는 그
 * 즉시 화면 하단에 실제 에러 메시지가 빨간 글씨로 뜬다 — 그 문구를 그대로 알려주면
 * 원인을 바로 알 수 있다. 실행 후 시트에 "__WIDE_TEST__" 행이 보이면 지워도 된다.
 */
/**
 * 정리용 — 디버깅 중 검증 오류로 중간에 끊긴 부분 삽입(No.열=9999로 표시됨)을
 * 지운다. 에디터에서 ▶ 실행하면 바로 지워지고, 지운 행 수가 로그에 뜬다.
 * (View → Logs 또는 실행 후 뜨는 팝업에서 확인 가능)
 */
function cleanupTestRows() {
  var ss = SpreadsheetApp.openById(SHEET_ID);
  var sheet = _findTabByNeedles(ss, ["MD", "AS"]);
  if (!sheet) throw new Error("tab not found");
  var data = sheet.getDataRange().getValues();
  var deleted = 0;
  for (var i = data.length - 1; i >= 0; i--) {
    if (data[i][0] === 9999) {
      sheet.deleteRow(i + 1);
      deleted++;
    }
  }
  Logger.log("삭제된 행 수: " + deleted);
}

/**
 * 정리용 — PORT-X IV 로 표기된 6건이 드롭다운 검증 때문에 제품명(사양) 칸이
 * 빈 채로 들어갔다(2026-09-21, 로마숫자 표기 문제로 발견). 시트엔 이미 같은
 * 모델이 "PORT-X 4" 로 등록돼 있어서 그 표기로 채워 넣는다. 제조번호로 찾아서
 * I열(9번째, 제품명(사양))만 채운다 — 다른 데이터는 안 건드림.
 */
function fixPortXProductNames() {
  var serials = [
    "GD-522013-20624", "GD-701083-20625", "GD-205129-20624",
    "GD-830086-20623", "GD-318040-20624", "GD-510059-20623",
  ];
  var ss = SpreadsheetApp.openById(SHEET_ID);
  var sheet = _findTabByNeedles(ss, ["MD", "AS"]);
  if (!sheet) throw new Error("tab not found");
  var data = sheet.getDataRange().getValues();
  var fixed = 0;
  for (var i = 1; i < data.length; i++) {
    if (serials.indexOf(data[i][9]) !== -1 && !data[i][8]) {
      sheet.getRange(i + 1, 9).setValue("PORT-X 4"); // 9번째 열 = 제품명(사양)
      fixed++;
    }
  }
  Logger.log("고친 행 수: " + fixed);
}

/**
 * 정리용 — 처음 111건 반영할 때 필터링을 빠뜨려서 GK(대리점) 채널이 아니라
 * 제노레이 자체 해외 법인(Genoray Shanghai/Turkey)이 직접 응대한 24건이 섞여
 * 들어갔다(2026-09-21, "법인 담당자꺼는 취합 안 한다" 는 방침 확인 후 발견).
 * No.열과 제조번호를 같이 대조해서(둘 다 맞아야) 정확히 그 24건만 지운다.
 */
function removeCorporateChannelRows() {
  var targets = {
    10017: "GMA-A26002-50722", 10026: "GCT-120210-70419", 10028: "GCT-120210-70419",
    10029: "GCT-308001-70422", 10038: "GMA-926006-50723", 10052: "GCT-112004-70419",
    10055: "GCT-020302-70420", 10058: "GCT-102902-70421", 10059: "GCT-120116-70417",
    10070: "GCT-102212-70418", 10076: "GCT-060107-70418", 10077: "GCT-120116-70417",
    10082: "GCT-071616-70418", 10084: "GCT-112515-70420", 10090: "GCT-209020-70422",
    10097: "GCT-120920-70421", 10099: "GMA-602001-50726", 10104: "GCT-121611-70421",
    10105: "GCT-111111-70420", 10106: "GCT-102712-70420", 10108: "GMA-926003-50723",
    10112: "GCT-120904-70421", 10113: "GCT-011805-70419", 10114: "GCT-041904-70418",
  };
  var ss = SpreadsheetApp.openById(SHEET_ID);
  var sheet = _findTabByNeedles(ss, ["MD", "AS"]);
  if (!sheet) throw new Error("tab not found");
  var data = sheet.getDataRange().getValues();
  var deleted = 0;
  for (var i = data.length - 1; i >= 0; i--) {
    var no = data[i][0];
    if (targets.hasOwnProperty(no) && data[i][9] === targets[no]) {
      sheet.deleteRow(i + 1);
      deleted++;
    }
  }
  Logger.log("삭제된 행 수: " + deleted + " / 24");
}

/**
 * 정리용(2단계 수정) — 기준을 다시 보니 Contact Point(GK vs 법인)가 아니라
 * charge_type(본사가 직접 처리했는지)이 맞는 기준이었다(사용자 확인, 2026-09-21).
 * GK 채널이라도 대리점이 자체 처리(charge_type=딜러사)한 19건은 취합 대상이
 * 아니라서 지운다 — removeCorporateChannelRows() 로 지운 24건 중 21건(본사 처리
 * 한 GS 20 + GT 1)은 이미 다시 넣었고(코드가 charge_type 기준으로 수정됨), 이번엔
 * 반대로 GK인데 딜러사가 처리한 것만 골라 지운다.
 */
function removeDealerHandledRows() {
  var targets = {
    10004: "ZEN-306901-10725", 10006: "ZEN-917003-10925", 10007: "ZEN-725004-A0225",
    10013: "ZEN-419005-10924", 10015: "GMA-319001-50726", 10016: "ZEN-905006-10825",
    10027: "GDP-617008-40422", 10050: "ZEN-620003-10725", 10054: "GMA-B04005-50725",
    10056: "ZEN-917007-10925", 10057: "ZEN-082605-11120", 10086: "GMA-718003-50725",
    10093: "ZEN-608010-10922", 10094: "ZEN-203004-10923", 10100: "ZEN-703004-A0226",
    10101: "ZEN-033105-10721", 10102: "ZEN-313002-A0225", 10103: "ZEN-102601-10817",
    10107: "GMA-816005-50724",
  };
  var ss = SpreadsheetApp.openById(SHEET_ID);
  var sheet = _findTabByNeedles(ss, ["MD", "AS"]);
  if (!sheet) throw new Error("tab not found");
  var data = sheet.getDataRange().getValues();
  var deleted = 0;
  for (var i = data.length - 1; i >= 0; i--) {
    var no = data[i][0];
    if (targets.hasOwnProperty(no) && data[i][9] === targets[no]) {
      sheet.deleteRow(i + 1);
      deleted++;
    }
  }
  Logger.log("삭제된 행 수: " + deleted + " / 19");
}

/**
 * 최종 정리(2026-09-22) — 그동안 여러 번 수정하면서(법인 처리 기준을 바꾸다가
 * 되돌리고, 외부 자동화가 행을 복제하는 바람에) No.열 10000대에 실수로 남은
 * 것들을 이번에 전부 다시 정확히 찾아서 지운다. **No.가 10000 미만인 행은
 * 원래부터 있던 데이터라 이 함수가 절대 건드리지 않는다** — No+제조번호 둘 다
 * 일치해야만 지운다. 21건(제노레이 상하이/터키 법인 소속 직원이 처리 — 우리
 * 본사 소속 아님) + 나머지 3건(예전 실수로 남은 중복/오채널) = 24건.
 */
function finalCleanup() {
  var targets = {
    10000: "ZEN-306901-10725", 10002: "ZEN-917003-10925", 10005: "GMA-B20002-50325",
    10112: "GMA-A26002-50722", 10113: "GCT-120210-70419", 10114: "GCT-308001-70422",
    10115: "GCT-120210-70419", 10116: "GCT-112004-70419", 10117: "GCT-020302-70420",
    10118: "GCT-102902-70421", 10119: "GCT-120116-70417", 10120: "GCT-102212-70418",
    10121: "GCT-060107-70418", 10122: "GCT-120116-70417", 10123: "GCT-071616-70418",
    10124: "GCT-112515-70420", 10125: "GCT-209020-70422", 10126: "GCT-120920-70421",
    10127: "GCT-121611-70421", 10128: "GCT-111111-70420", 10129: "GCT-102712-70420",
    10130: "GCT-120904-70421", 10131: "GCT-011805-70419", 10132: "GCT-041904-70418",
  };
  var ss = SpreadsheetApp.openById(SHEET_ID);
  var sheet = _findTabByNeedles(ss, ["MD", "AS"]);
  if (!sheet) throw new Error("tab not found");
  var data = sheet.getDataRange().getValues();
  var deleted = 0;
  for (var i = data.length - 1; i >= 0; i--) {
    var no = data[i][0];
    if (no < 10000) continue; // 안전장치: 원래 있던 데이터는 절대 안 지움
    if (targets.hasOwnProperty(no) && data[i][9] === targets[no]) {
      sheet.deleteRow(i + 1);
      deleted++;
    }
  }
  Logger.log("삭제된 행 수: " + deleted + " / 24");
}

function testWriteWide() {
  var ss = SpreadsheetApp.openById(SHEET_ID);
  var sheet = _findTabByNeedles(ss, ["MD", "AS"]);
  if (!sheet) throw new Error("tab not found");
  var row = ["__WIDE_TEST__", 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16];
  sheet.getRange(sheet.getLastRow() + 1, 1, 1, row.length).setValues([row]);
}

function _json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
