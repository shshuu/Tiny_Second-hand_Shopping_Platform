(() => {
  const input = document.querySelector("[data-image-input]");
  const countNode = document.getElementById("image-count");
  if (!input || !countNode) return;
  input.addEventListener("change", () => {
    const count = input.files.length;
    if (count > 5) {
      input.value = "";
      countNode.textContent = "이미지는 최대 5장만 선택할 수 있습니다. 선택을 다시 해주세요.";
      return;
    }
    countNode.textContent = `선택한 이미지: ${count}장 / 최대 5장`;
  });
})();
