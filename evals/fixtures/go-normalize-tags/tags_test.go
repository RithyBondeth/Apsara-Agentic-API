package tags

import (
	"reflect"
	"testing"
)

func TestNormalizeTags(t *testing.T) {
	got := NormalizeTags([]string{" Go ", "PYTHON", "go", "", " python ", "Rust"})
	want := []string{"go", "python", "rust"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %#v, want %#v", got, want)
	}
}

func TestNormalizeTagsEmpty(t *testing.T) {
	if got := NormalizeTags(nil); len(got) != 0 {
		t.Fatalf("got %#v, want empty", got)
	}
}
